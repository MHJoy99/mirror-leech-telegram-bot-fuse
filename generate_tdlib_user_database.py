from asyncio import run, to_thread
from os import getcwd
from sys import argv

from pytdbot import Client

OUTPUT_DIR = argv[1] if len(argv) > 1 else f"{getcwd()}/tdlib_user"
api_id = input("Enter api_id: ").strip()
api_hash = input("Enter api_hash: ").strip()
phone = input("Enter phone number (e.g. +880171...): ").strip()


async def main():
    client = Client(
        api_id=api_id,
        api_hash=api_hash,
        files_directory=OUTPUT_DIR,
        use_file_database=True,
        use_chat_info_database=True,
        use_message_database=True,
        database_encryption_key="mltbmltb",
        td_verbosity=1,
        user_bot=True,
    )

    @client.on_updateAuthorizationState()
    async def handle_auth(_, __):
        state = client.authorization_state
        print(f"auth_state={state}", flush=True)
        match state:
            case "authorizationStateReady":
                print("LOGIN SUCCESSFUL", flush=True)
                await client.stop()
            case "authorizationStateWaitTdlibParameters":
                await client.set_td_parameters()
            case "authorizationStateWaitPhoneNumber":
                res = await client.setAuthenticationPhoneNumber(
                    phone_number=phone
                )
                if res["@type"] != "ok":
                    print(res["message"], flush=True)
            case "authorizationStateWaitCode":
                code = input("Enter code: ").strip()
                res = await client.checkAuthenticationCode(code=code)
                if res["@type"] != "ok":
                    print(res["message"], flush=True)
            case "authorizationStateWaitPassword":
                password = input("Enter password: ").strip()
                res = await client.checkAuthenticationPassword(password=password)
                if res["@type"] != "ok":
                    print(res["message"], flush=True)

    await client.start()
    await client.idle()

run(main())
