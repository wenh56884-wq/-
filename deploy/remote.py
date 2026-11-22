"""远程执行 / 上传工具（密码登录）。

用法：
  python remote.py exec "<shell command>"
  python remote.py put <local> <remote>
  python remote.py putbytes <local> <remote>   # 与 put 相同，但用于二进制
"""
import os
import sys

import paramiko

HOST = os.environ.get("QH_HOST", "101.34.254.115")
USER = os.environ.get("QH_USER", "root")
PWD = os.environ.get("QH_PWD", "")


def connect():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, port=22, username=USER, password=PWD,
              timeout=25, banner_timeout=30, auth_timeout=30,
              look_for_keys=False, allow_agent=False)
    return c


def main():
    action = sys.argv[1]
    c = connect()
    try:
        if action == "exec":
            cmd = sys.argv[2]
            stdin, stdout, stderr = c.exec_command(cmd, timeout=3000)
            out = stdout.read().decode("utf-8", "replace")
            err = stderr.read().decode("utf-8", "replace")
            code = stdout.channel.recv_exit_status()
            sys.stdout.buffer.write(out.encode("utf-8", "replace"))
            if err.strip():
                sys.stdout.buffer.write(("\n[stderr]\n" + err).encode("utf-8", "replace"))
            sys.stdout.buffer.write(f"\n[exit={code}]\n".encode("utf-8"))
            sys.stdout.flush()
            sys.exit(0 if code == 0 else 1)

        elif action == "put":
            local, remote = sys.argv[2], sys.argv[3]
            sftp = c.open_sftp()
            size = os.path.getsize(local)
            last = [0]

            def cb(done, total):
                pct = int(done * 100 / total) if total else 0
                if pct >= last[0] + 10:
                    last[0] = pct
                    sys.stdout.buffer.write(f"  upload {pct}%\n".encode())
                    sys.stdout.flush()

            sftp.put(local, remote, callback=cb)
            sftp.close()
            sys.stdout.buffer.write(f"  done {size/1048576:.1f} MB -> {remote}\n".encode())
        else:
            raise SystemExit(f"unknown action {action}")
    finally:
        c.close()


if __name__ == "__main__":
    main()
