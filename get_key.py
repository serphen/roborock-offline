#!/usr/bin/env python3
import asyncio
import getpass
import sys
from roborock.web_api import RoborockApiClient

async def main():
    print("\n==============================================")
    print("   Roborock account login")
    print("   (Used only once to fetch the local key)")
    print("==============================================")
    
    email = input("Roborock email: ").strip()
    if not email:
        print("Email required.")
        sys.exit(1)
        
    password = getpass.getpass("Password: ").strip()
    if not password:
        print("Password required.")
        sys.exit(1)

    print("\nConnecting to Roborock cloud...")
    
    try:
        api = RoborockApiClient(username=email)
        user_data = await api.pass_login(password)
        home_data = await api.get_home_data_v3(user_data)
        devices = home_data.get_all_devices()
    except Exception as e:
        print(f"Login or fetch error: {e}")
        sys.exit(1)

    if not devices:
        print("No devices found on this account.")
        sys.exit(1)

    selected = None
    if len(devices) == 1:
        selected = devices[0]
        print(f"Found 1 device: {selected.name}")
    else:
        print(f"\nFound {len(devices)} devices:")
        for i, d in enumerate(devices):
            print(f"   {i+1}. {d.name} (ID: {d.duid})")
        
        while True:
            try:
                choice = input(f"\nSelect device number (1-{len(devices)}): ")
                idx = int(choice) - 1
                if 0 <= idx < len(devices):
                    selected = devices[idx]
                    break
                print("Invalid number.")
            except ValueError:
                print("Please enter a number.")

    print(f"\nKey extracted successfully for: {selected.name}")
    
    # Save to a file that shell script can source
    with open("/tmp/roborock_key.env", "w") as f:
        f.write(f"ROBOROCK_KEY='{selected.local_key}'\n")
        f.write(f"ROBOROCK_DUID='{selected.duid}'\n")
        f.write(f"ROBOROCK_NAME='{selected.name}'\n")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(1)