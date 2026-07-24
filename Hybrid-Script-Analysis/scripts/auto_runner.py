#!/usr/bin/env python3
"""自动化批量视频拆解执行器 — 扫描查重 + 批量拆解待处理"""
import sys
import time
import threading
from pathlib import Path

# 确保能导入 web_app
sys.path.insert(0, str(Path(__file__).resolve().parent))
from web_app import (
    scan_teardown_queue,
    run_queue_job,
    JOBS,
    JOBS_LOCK,
    OUTPUTS_DIR,
    SKILL_ROOT,
    local_paths,
)

VIDEO_DIR, SCRIPT_DIR = local_paths()


def main():
    print("=" * 60)
    print("📋 步骤1: 扫描查重")
    print("=" * 60)
    print(f"  视频目录: {VIDEO_DIR}")
    print(f"  脚本目录: {SCRIPT_DIR}")
    print()

    scan = scan_teardown_queue(VIDEO_DIR, SCRIPT_DIR)
    summary = scan["summary"]
    print(f"✅ 扫描完成!")
    print(f"  总视频数:    {summary['total']}")
    print(f"  待拆解:      {summary['pending']}")
    print(f"  重复跳过:    {summary['skipped']}")
    print(f"  无法识别ID:  {summary['missing_id']}")
    print(f"  已有脚本:    {summary['script_ids']}")
    print()

    pending = scan["pending"]
    skipped = scan["skipped"]
    missing_id = scan["missing_id"]

    if skipped:
        print("--- 重复跳过 ---")
        for item in skipped:
            print(f"  ⏭️ {item['relative_path']} -> {item.get('duplicate_script', 'N/A')}")
        print()

    if missing_id:
        print("--- 无法识别ID ---")
        for item in missing_id:
            print(f"  ❓ {item['relative_path']}")
        print()

    if pending:
        print("--- 待拆解列表 ---")
        for i, item in enumerate(pending, 1):
            print(f"  {i}. [{item['product']}] {item['name']}")
        print()

    # === 步骤2: 批量拆解 ===
    if not pending:
        print("=" * 60)
        print("✅ 没有待拆解视频，任务结束。")
        print("=" * 60)
        return {
            "scan": scan,
            "job": None,
            "status": "nothing_to_do",
        }

    print("=" * 60)
    print("🔧 步骤2: 批量拆解待处理")
    print("=" * 60)
    print(f"  待处理数量: {len(pending)}")
    print()

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    output_dir = OUTPUTS_DIR / f"{timestamp}_auto"
    output_dir.mkdir(parents=True, exist_ok=True)

    import uuid
    job_id = uuid.uuid4().hex[:12]

    # 在后台线程运行批量拆解
    print(f"🚀 启动批量拆解 (job_id={job_id})...\n")

    thread = threading.Thread(
        target=run_queue_job,
        args=(job_id, pending, output_dir, SCRIPT_DIR),
        daemon=False,
    )
    thread.start()

    # 轮询进度
    last_completed = 0
    while thread.is_alive():
        time.sleep(2)
        with JOBS_LOCK:
            job = JOBS.get(job_id, {})
        completed = job.get("completed", 0)
        failed = job.get("failed", 0)
        total = job.get("total", len(pending))
        if completed != last_completed:
            print(f"  📊 进度: {completed}/{total} 完成, {failed} 失败")
            last_completed = completed

    thread.join()

    # 最终结果
    with JOBS_LOCK:
        job = JOBS.get(job_id, {})

    print()
    print("=" * 60)
    print("📊 批量拆解完成!")
    print("=" * 60)
    print(f"  状态:     {job.get('status', 'unknown')}")
    print(f"  总任务:   {job.get('total', 0)}")
    print(f"  完成:     {job.get('completed', 0)}")
    print(f"  失败:     {job.get('failed', 0)}")
    final_outputs = job.get("final_outputs", [])
    if final_outputs:
        print(f"  输出文件: {len(final_outputs)} 个")
        for f in final_outputs:
            print(f"    📄 {f}")
    if job.get("error"):
        print(f"  ❌ 错误: {job['error']}")
    print()

    return {
        "scan": scan,
        "job": job,
        "status": job.get("status", "unknown"),
    }


if __name__ == "__main__":
    result = main()
    # 输出 JSON 结果供 automation 解析
    import json
    print("===RESULT_JSON===")
    print(json.dumps({
        "scan_summary": result["scan"]["summary"],
        "job_status": result["job"]["status"] if result["job"] else "nothing_to_do",
        "job_completed": result["job"].get("completed", 0) if result["job"] else 0,
        "job_failed": result["job"].get("failed", 0) if result["job"] else 0,
        "final_outputs": result["job"].get("final_outputs", []) if result["job"] else [],
    }, ensure_ascii=False, indent=2))
