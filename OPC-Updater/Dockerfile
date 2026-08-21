FROM public.ecr.aws/docker/library/docker:27-cli

RUN apk add --no-cache git python3

COPY server.py /opt/opc-updater/server.py

EXPOSE 18888
CMD ["python3", "-u", "/repo/OPC-Updater/server.py"]
