# /// script
# requires-python = ">=3.12"
# dependencies = ["aiohttp", "rich", "tqdm"]
# ///

"""Purge invalid CPA auth files."""
import os
import argparse
import asyncio
import subprocess as sp

from dataclasses import dataclass, asdict

from collections import Counter
try:
    import aiohttp
except ModuleNotFoundError:
    sp.run("pip install -q aiohttp")
    import aiohttp
    from aiohttp import ClientResponseError, ClientError

try:
    from rich import print
    from rich.panel import Panel
except ModuleNotFoundError:
    sp.run("pip install -q rich")
    from rich import print
    from rich.panel import Panel

try:
    from tqdm import tqdm
except ModuleNotFoundError:
    sp.run("pip install -q tqdm")
    from tqdm import tqdm


@dataclass(frozen=True)
class Args:
    secret_key: str
    base_url: str
    provider: str
    port: int | str
    dry_run: bool

    def asdict(self):
        return asdict(self)

def validate_port(port: str) -> int | str:
    """Validate port number, default to 8317 if invalid."""
    if not port.strip():
        return ""

    try:
        port_num = int(port)
    except ValueError:
        print(f"[Warning] Invalid port '{port}', using default 8317")
        return 8317

    if not (1 <= port_num <= 65535):
        print(f"[Warning] Port {port_num} out of range (1-65535), using default 8317")
        return 8317

    return port_num


def parse_args() -> Args:
    parser = argparse.ArgumentParser(
        description="CLI tool for purging invalid CPA auth files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples (uv run %(prog)s or python %(prog)s):
  %(prog)s -h
  %(prog)s
  %(prog)s --port 8318
  %(prog)s --provider qwen --port 8787
  %(prog)s --secret-key mykey --base-url https://api.example.com -p qwen
  %(prog)s --secret-key mykey --base-url https://api.example.com -p qwen --port ""
  %(prog)s --dry-run
        """
    )

    parser.add_argument(
        "-k", "--secret-key",
        default=os.getenv("CPA_SECRET_KEY"),
        help="Secret API key (default: CPA_SECRET_KEY env var)"
    )

    parser.add_argument(
        "-u", "--base-url",
        default="http://127.0.0.1",
        help="Base URL of the API endpoint (default: http://127.0.0.1)"
    )

    parser.add_argument(
        "-p", "--provider",
        default="codex",
        # choices=["codex", "qwen", "germini-cli", "antigravity", "all"],
        help="Service provider name, can set to all (default: codex)"
    )

    parser.add_argument(
        "--port",
        type=validate_port,
        default=8317,
        help="Port number to listen on (default: 8317, falls back to 8317 if invalid, can set to \"\")"
    )

    parser.add_argument(
        "-d", "--dry-run",
        action="store_true",
        default=False,
        help="Show what would be done without making actual changes"
    )

    parsed = parser.parse_args()
    if not parsed.secret_key:
        parsed.secret_key = input("贴上cpa secret-key: ")

    parsed.secret_key = parsed.secret_key.strip()

    # Validate secret key is provided somehow
    if not parsed.secret_key:
        parser.error("--secret-key or CPA_SECRET_KEY environment variable is required")

    return Args(
        secret_key=parsed.secret_key,
        base_url=parsed.base_url.rstrip("/"),
        provider=parsed.provider,
        port=parsed.port,
        dry_run=parsed.dry_run,
    )


async def fetch_files(base_url, headers, check_status_only=True):
    total = os.getenv("CPA_TIMEOUT")
    if total:
        try:
            total = float(total)
        except Exception:
            total = 180
    else:
        total = 180
    timeout = aiohttp.ClientTimeout(total=total)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(
                f"{base_url}/auth-files",
                headers=headers,
            ) as response:
                # print(f"Content-Type: {response.headers.get('content-type')}")

                if check_status_only:
                    if not response.status == 200:
                        print(f"{response.status=}")
                        text = await response.text()
                        print(f"{text[:200]}")
                    return response.status

                if response.status == 200:
                    data = await response.json()
                    files = data.get('files', [])
                    print(f"Found {len(files)} files")
                    return files
                else:
                    text = await response.text()
                    print(f"{text[:200]}")
                    return []
    except Exception as e:
        print(f"{e=}")
        raise
        # return e


async def purge(base_url: str, headers: dict, name: str, session: aiohttp.ClientSession | None = None):
    close_session = session is None
    if session is None:
        session = aiohttp.ClientSession()
    try:
        async with session.delete(
            url=base_url + "/auth-files",
            params={"name": name},
            headers=headers,
        ) as response:
            response.raise_for_status()  # Raise on 4xx/5xx
            return await response.json()
    except ClientResponseError as e:
        print(f"HTTP error {e.status}: {e.message}")
        raise
    except ClientError as e:
        print(f"Connection error: {e}")
        raise
    finally:
        if close_session:
            await session.close()

async def main():
    args = parse_args()

    # secret-key in config.yaml
    # TOKEN = os.getenv("CPA_SECRET_KEY") or '<secret-key>'
    TOKEN = args.secret_key

    # assert not TOKEN == '<secret-key>', "Set CPA_API_KEY or modify '<secret-key>' in the source file"

    # PORT = os.getenv("CPA_PORT", "8317")
    PORT = args.port

    print(f"Use {PORT=}")

    # BASE_URL = f'http://127.0.0.1:{PORT}/v0/management'
    if PORT:
        BASE_URL = f'{args.base_url}:{PORT}/v0/management'
    else:
        BASE_URL = f'{args.base_url}/v0/management'

    HEADERS = {
        "Authorization": f"Bearer {TOKEN}"
    }

    try:
        # status = asyncio.run(fetch_files(BASE_URL, HEADERS))
        status = await fetch_files(BASE_URL, HEADERS)
    except Exception as e:
        raise SystemExit(e)

    if not status == 200:
        print(f"{args.asdict()}")
        print("Check previous error message, base_url and secret_key (secret-key in config.yaml) etc and try again")
        raise SystemExit(1)
    msg = """\
diggin…… 文件多（几千几万）或服务器负载太高的话可能需时较长。
出现超时错误时（e=TimeoutError()）可设环境变量CPA_TIMEOUT，例如set CPA_TIMEOUT=300/export CPA_TIMEOUT=300 (预设超时180秒）"""
    print(Panel(f"[bold yellow]{msg}[/bold yellow]", border_style="yellow"))

    try:
        # files = asyncio.run(fetch_files(BASE_URL, HEADERS, check_status_only=False))
        files = await fetch_files(BASE_URL, HEADERS, check_status_only=False)
    except Exception as e:
        raise SystemExit(e)

    total_files = len(files)
    _ = Counter(elm.get("provider") for elm in files)
    print(f"{total_files=}, {dict(_)}")
    print(dict(Counter(elm.get("status") for elm in files)))

    providers = Counter(elm.get("provider") for elm in files)
    for provider in providers:
       print(f"""{provider=}, {dict(Counter(elm.get("status") for elm in files if elm['provider'] == provider))}""")

    print(Panel(f"发现 [bold yellow]{total_files}[/bold yellow] 个文件", title="[bold green]净化工具[/bold green]"))

    if args.provider.lower() in ["all"]:
        files_to_purge = []
        _ = """
        for provider in providers:
            # del_cond = file.get("provider") == provider and (file.get("status") == "error" or file.get("status") == "disabled")
            # _ = [file for file in files if del_cond]
            p_files = []
            for file in files:
                if del_cond = file.get("provider") == provider and (file.get("status") == "error" or file.get("status") == "disabled"):
                    p_files.append(file)
            files_to_purge.extend(_)
        """
        for file in files:
            if file.get("status") == "error" or file.get("status") == "disabled":
               files_to_purge.append(file)
    else:
        #
        # files_to_purge = [file for file in files if file.get("provider") == args.provider and file.get("status") == "error"]
        files_to_purge = []
        for file in files:
            del_cond = file.get("provider") == args.provider and (file.get("status") == "error" or file.get("status") == "disabled")
            if del_cond:
                files_to_purge.append(file)

    if args.dry_run:
        print(Panel("[bold yellow] dry-run [/bold yellow]： 不会真的删…… ", border_style="yellow"))
    # print(f"Found {len(files_to_purge)} ")
    print()
    print(Panel(f"[bold green]✓ 需删除文件[/bold green]： {len(files_to_purge)}", border_style="green"))

    n_success = 0
    _ = """
    for file in tqdm(files_to_purge):
        try:
            if not args.dry_run:
                asyncio.run(purge(BASE_URL, HEADERS, file['name']))
            n_success += 1
        except Exception as e:
            print(e)
    # """
    if args.dry_run:
        # Just simulate progress
        for _ in tqdm(files_to_purge, total=len(files_to_purge)):
            n_success += 1
    else:
        tasks = [
            asyncio.create_task(purge(BASE_URL, HEADERS, file['name']))
            for file in files_to_purge
        ]

        for coro in tqdm(asyncio.as_completed(tasks), total=len(tasks)):
            try:
                await coro
                n_success += 1
            except Exception as e:
                print(e)

    print(Panel(f"[bold green]✓ 删除文件[/bold green]： {n_success}", border_style="green"))

if __name__ == "__main__":
	asyncio.run(main())
