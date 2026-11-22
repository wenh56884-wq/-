"""SSH 分块流式上传（不依赖 SFTP，规避长连接被断开）。

服务器 SFTP 写文件报 ENOENT、单连接灌 10MB 会被断，故按 2MB 分块、
每块独立建连追加写入，最后校验 md5。

用法：QH_PWD=... python deploy/push.py <local> <remote> [chunk_mb]
"""
import hashlib
import os
import sys

import paramiko

HOST = os.environ.get("QH_HOST", "101.34.254.115")
USER = os.environ.get("QH_USER", "root")
PWD = os.environ.get("QH_PWD", "")


def _conn() -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, port=22, username=USER, password=PWD, timeout=25,
                   banner_timeout=30, auth_timeout=30,
                   look_for_keys=False, allow_agent=False)
    return client


def main() -> None:
    local, remote = sys.argv[1], sys.argv[2]
    chunk = int(float(sys.argv[3]) * 1048576) if len(sys.argv) > 3 else 2 * 1048576
    total = os.path.getsize(local)
    pos, idx = 0, 0
    with open(local, "rb") as fh:
        while pos < total:
            fh.seek(pos)
            data = fh.read(chunk)
            redirect = ">" if idx == 0 else ">>"
            client = _conn()
            try:
                stdin, stdout, stderr = client.exec_command(
                    f"cat {redirect} {remote}", timeout=600)
                stdin.write(data)
                stdin.flush()
                stdin.channel.shutdown_write()
                code = stdout.channel.recv_exit_status()
                err = stderr.read().decode("utf-8", "replace").strip()
            finally:
                client.close()
            pos += len(data)
            idx += 1
            print(f"  chunk {idx}: {len(data)/1048576:.2f} MB -> {pos*100//total}% (exit={code})",
                  flush=True)
            if err:
                print("   stderr:", err[:200])
            if code != 0:
                raise SystemExit("chunk failed")

    client = _conn()
    try:
        _, stdout, _ = client.exec_command(f"md5sum {remote}; stat -c %s {remote}", timeout=300)
        print("  remote:", stdout.read().decode().strip().replace("\n", " | "))
    finally:
        client.close()
    print("  local :", hashlib.md5(open(local, "rb").read()).hexdigest(), total)


if __name__ == "__main__":
    main()
