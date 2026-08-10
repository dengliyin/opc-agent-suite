from __future__ import annotations

import argparse
import json

from . import web


RESULT_PREFIX = "OPC_PIPELINE_RESULT="


def catalog() -> dict:
    warnings: list[str] = []
    try:
        profiles = web.list_bitbrowser_profiles().get("profiles", [])
    except Exception as exc:
        profiles = []
        warnings.append(f"读取发布账号失败：{exc}")
    config = web.load_publish_config()
    libraries = web.load_title_library()
    records = web.load_publish_records()
    return {
        "profiles": profiles,
        "libraries": list(libraries.values()),
        "videos": [item for item in web.scan_finished_videos(libraries, records) if not item.get("published")],
        "product_links_by_store": config.get("product_links_by_store") or {},
        "product_short_names": config.get("product_short_names") or {},
        "warnings": warnings,
    }


def resolve_mapping(args: argparse.Namespace) -> dict:
    data = catalog()
    profile = next((item for item in data["profiles"] if item.get("id") == args.profile_id), None)
    if not profile:
        raise ValueError("发布账号不存在")
    config = {
        "product_links_by_store": data["product_links_by_store"],
        "product_short_names": data["product_short_names"],
    }
    product_id = web.product_id_for_account(config, args.product_code, args.country, profile)
    short_name = str(((config["product_short_names"].get(args.product_code) or {}).get(args.country) or ""))
    if not product_id:
        raise ValueError(f"商品映射缺失：{args.product_code} / {args.country} / {profile.get('name', '')}")
    if not short_name:
        raise ValueError(f"商品简称缺失：{args.product_code} / {args.country}")
    return {"profile": profile, "product_id": product_id, "product_short_name": short_name}


def publish(args: argparse.Namespace) -> dict:
    return web.publish_tiktok_video(
        args.profile_id,
        args.video_path,
        args.caption,
        args.product_id,
        args.product_short_name,
        True,
        "public",
        "headless",
        True,
    )


def close_profile(args: argparse.Namespace) -> dict:
    return web.close_bitbrowser_profile({"profile_id": args.profile_id})


def main() -> int:
    parser = argparse.ArgumentParser(description="Shared publishing bridge for the automatic pipeline.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("catalog")
    mapping_parser = subparsers.add_parser("mapping")
    mapping_parser.add_argument("--profile-id", required=True)
    mapping_parser.add_argument("--product-code", required=True)
    mapping_parser.add_argument("--country", required=True)
    publish_parser = subparsers.add_parser("publish")
    publish_parser.add_argument("--profile-id", required=True)
    publish_parser.add_argument("--video-path", required=True)
    publish_parser.add_argument("--caption", required=True)
    publish_parser.add_argument("--product-id", required=True)
    publish_parser.add_argument("--product-short-name", required=True)
    close_parser = subparsers.add_parser("close")
    close_parser.add_argument("--profile-id", required=True)
    args = parser.parse_args()
    try:
        if args.command == "catalog":
            result = catalog()
        elif args.command == "mapping":
            result = resolve_mapping(args)
        elif args.command == "publish":
            result = publish(args)
        else:
            result = close_profile(args)
        print(RESULT_PREFIX + json.dumps(result, ensure_ascii=False), flush=True)
        return 0
    except Exception as exc:
        print(RESULT_PREFIX + json.dumps({"error": str(exc)}, ensure_ascii=False), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
