from asyncio import run, sleep
from os import getcwd, path
from sys import argv

from pytdbot import Client


COUNT = int(argv[1]) if len(argv) > 1 else 4
BASE_DIR = argv[2] if len(argv) > 2 else f"{getcwd()}/tdlib_user"


def _db_path(index: int) -> str:
    return BASE_DIR if index == 1 else f"{BASE_DIR}_{index}"


def _free_start_index() -> int:
    start = 2 if path.basename(BASE_DIR) == "tdlib_user" else 1
    while path.exists(_db_path(start)):
        start += 1
    return start


async def _login_one(api_id: str, api_hash: str, phone: str, output_dir: str):
    client = Client(
        api_id=api_id,
        api_hash=api_hash,
        files_directory=output_dir,
        use_file_database=True,
        use_chat_info_database=True,
        use_message_database=True,
        database_encryption_key="mltbmltb",
        td_verbosity=1,
        user_bot=True,
    )

    await client.start()
    try:
        while True:
            state = client.authorization_state
            print(f"auth_state={state}", flush=True)
            if state == "authorizationStateReady":
                me = await client.getMe()
                return {
                    "db": output_dir,
                    "id": me.id,
                    "username": me.usernames.editable_username,
                    "premium": bool(me.is_premium),
                }
            if state == "authorizationStateWaitTdlibParameters":
                res = await client.set_td_parameters()
                print(f"set_td_parameters={res['@type']}", flush=True)
            elif state == "authorizationStateWaitPhoneNumber":
                res = await client.setAuthenticationPhoneNumber(phone_number=phone)
                print(f"setAuthenticationPhoneNumber={res['@type']}", flush=True)
                if res["@type"] == "error":
                    print(res["message"], flush=True)
                    return
            elif state == "authorizationStateWaitCode":
                code = input("Enter code: ").strip()
                res = await client.checkAuthenticationCode(code=code)
                print(f"checkAuthenticationCode={res['@type']}", flush=True)
                if res["@type"] == "error":
                    print(res["message"], flush=True)
                    return
            elif state == "authorizationStateWaitPassword":
                password = input("Enter password: ").strip()
                res = await client.checkAuthenticationPassword(password=password)
                print(f"checkAuthenticationPassword={res['@type']}", flush=True)
                if res["@type"] == "error":
                    print(res["message"], flush=True)
                    return
            elif state == "authorizationStateClosed":
                print("AUTH_CLOSED", flush=True)
                return None
            await sleep(1)
    finally:
        await client.stop()


async def main():
    api_id = input("Enter api_id: ").strip()
    api_hash = input("Enter api_hash: ").strip()
    created_paths = []
    seen_ids = set()
    start_index = _free_start_index()
    for index in range(start_index, start_index + COUNT):
        print(f"\n=== TDLib account {index}/{COUNT} ===", flush=True)
        phone = input("Enter phone number (e.g. +880171...): ").strip()
        db_path = _db_path(index)
        result = await _login_one(api_id, api_hash, phone, db_path)
        if not result:
            print(f"LOGIN_FAILED db={db_path}", flush=True)
            continue
        created_paths.append(db_path)
        print(
            f"LOGIN_OK db={db_path} id={result['id']} username={result['username']} premium={result['premium']}",
            flush=True,
        )
        if result["id"] in seen_ids:
            print(
                "WARNING: this is the same Telegram account as a previous login, so it will not give you real multi-account speed.",
                flush=True,
            )
        seen_ids.add(result["id"])
        if index != COUNT:
            cont = input("Press Enter for next account, or type stop to end: ").strip()
            if cont.lower() == "stop":
                break

    if len(seen_ids) <= 1 and len(created_paths) > 1:
        print(
            "\nWARNING: all created TDLib databases belong to the same Telegram account.",
            flush=True,
        )
        print(
            "To get real parallel upload speed, log in with different phone numbers/accounts.",
            flush=True,
        )

    print("\nPaste this into config_local.py:", flush=True)
    print("TDLIB_USER_DB_PATHS = [", flush=True)
    for path in created_paths:
        print(f'    "{path.split("/")[-1]}",', flush=True)
    print("]", flush=True)


if __name__ == "__main__":
    run(main())
