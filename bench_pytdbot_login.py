import asyncio
import sys

from pytdbot import Client


API_ID = int(sys.argv[1]) if len(sys.argv) > 1 else 0
API_HASH = sys.argv[2] if len(sys.argv) > 2 else ""
PHONE = sys.argv[3] if len(sys.argv) > 3 else ""
CODE = sys.argv[4] if len(sys.argv) > 4 else None
PASSWORD = sys.argv[5] if len(sys.argv) > 5 else None
FILES_DIR = "/app/tdlib_user"


async def main():
    client = Client(
        api_id=API_ID,
        api_hash=API_HASH,
        files_directory=FILES_DIR,
        use_file_database=False,
        database_encryption_key="mltbmltb",
        td_verbosity=1,
        user_bot=True,
    )

    await client.start()
    try:
        for _ in range(240):
            state = client.authorization_state
            print(f"auth_state={state}", flush=True)
            if state == "authorizationStateReady":
                me = await client.getMe()
                print(
                    f"AUTH_OK id={me.id} username={me.usernames.editable_username} premium={me.is_premium}",
                    flush=True,
                )
                return 0
            if state == "authorizationStateWaitTdlibParameters":
                res = await client.set_td_parameters()
                print(f"set_td_parameters={res['@type']}", flush=True)
            elif state == "authorizationStateWaitPhoneNumber":
                res = await client.setAuthenticationPhoneNumber(phone_number=PHONE)
                print(f"setAuthenticationPhoneNumber={res['@type']}", flush=True)
            elif state == "authorizationStateWaitCode":
                print("WAIT_CODE", flush=True)
                if not CODE:
                    return 2
                res = await client.checkAuthenticationCode(code=CODE)
                print(
                    f"checkAuthenticationCode={res['@type']} {getattr(res, 'message', '')}",
                    flush=True,
                )
                if res["@type"] == "error":
                    return 3
            elif state == "authorizationStateWaitPassword":
                print("WAIT_PASSWORD", flush=True)
                if not PASSWORD:
                    return 4
                res = await client.checkAuthenticationPassword(password=PASSWORD)
                print(
                    f"checkAuthenticationPassword={res['@type']} {getattr(res, 'message', '')}",
                    flush=True,
                )
                if res["@type"] == "error":
                    return 5
            elif state == "authorizationStateClosed":
                print("AUTH_CLOSED", flush=True)
                return 6
            await asyncio.sleep(1)
        print("AUTH_TIMEOUT", flush=True)
        return 7
    finally:
        await client.stop()


raise SystemExit(asyncio.run(main()))
