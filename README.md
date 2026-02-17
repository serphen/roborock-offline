# Roborock offline kit

**Transform your Roborock vacuum into an offline device.**

Recent Roborock robots need a constant internet connection. Without it, they refuse to work, lose features, or disconnect from Wi-Fi. Third-party firmwares are not supported on recent models.

We run a fake Roborock server on a small mini-router. The robot believes it's talking to the cloud, but everything stays local. You keep full control through the official Roborock app — no modified firmware needed. Commands go directly from the phone to the robot without intermediary.

### How it works

You need three things: a **mini-router** (like a GL.iNet), an **old phone**, and your **robot**.

1. We create a Wi-Fi network with **no internet** on the mini-router.
2. We run scripts on it that pretend to be the Roborock cloud.
3. The phone connects to this network and controls the robot through the official app.
4. The robot connects to this network and works normally — map, camera, remote control.

**No data ever leaves this network.** Video, audio, and maps stay between the phone and the robot.

*Advanced users can achieve the same setup using a VLAN instead of a dedicated mini-router.*

## Prerequisites

*   **Isolated router**: A GL.iNet router or any OpenWRT device.
    *   *Tested on*: **GL.iNet GL-MT3000 (Beryl AX)** (Recommended for better range/CPU).
    *   *Works with*: Cheaper models like **GL-MT300N-V2 (Mango)** should also work, but with shorter Wi-Fi range.
*   **SSH client**: Basic terminal access.

## Quick start guide (GL.iNet router)

### Step 1: Prepare the router (internet needed)
*Your router needs internet access JUST for the installation.*

1.  Connect your PC to the GL.iNet router using the Wi-Fi password printed on the bottom of the router, then go to http://192.168.8.1.
2.  Choose an admin password.
3.  Go to Admin Panel -> **Internet** -> **Repeater**. Select your home Wi-Fi and enter its password. This gives the router temporary internet access needed for installation.

### Step 2: Install the Roborock app
1.  Connect the phone you plan to dedicate to use the robot to the router's Wi-Fi.
2.  Install the official [Roborock app](https://play.google.com/store/apps/details?id=com.roborock.smart).
3.  Create an account and sign in.

### Step 3: Install the scripts on the router
1.  SSH into the router (`ssh root@192.168.8.1`). When prompted, enter the admin password you chose earlier. Then run the installer:

    ```bash
    wget -O install.sh https://raw.githubusercontent.com/serphen/roborock-offline/main/install.sh && sh install.sh
    ```
    *(The script will ask for your **Roborock email & password** to fetch the robot key. The request is sent directly to Roborock servers).*

### Step 4: Lockdown
1.  **Disconnect the new router from internet**: Go to Admin Panel -> **Internet** -> **Disconnect Repeater**. Unplug any WAN cable.
2.  **Verify**: Your new router should have NO internet access.

### Step 5: Add the devices
*Only NOW you connect the robot.*

1.  **Reset robot Wi-Fi**: Hold specific buttons (usually Home + Spot) until "Resetting Wi-Fi".
2.  **Pair**: Open the Roborock app on the phone, add the robot, and connect it to the isolated router's Wi-Fi.
    *   *Note: The app might complain about no internet. Ignore it. The proxy will handle it.*

Your dedicated phone can now control the robot, view the map, and see the camera stream.
Since the isolated router has no internet connection, **no video, audio, or map data can ever be sent to the cloud.**

---

## How it works (technical)

Two scripts run on your isolated router to emulate cloud connectivity:

1.  **Fake cloud (KeepAlive server - port 8053)**:
    *   The robot pings the cloud to check connectivity.
    *   Our script answers "Pong!". The robot stays connected to Wi-Fi.

2.  **Fake app proxy (MitM - port 58867)**:
    *   The app asks for a "turn server" to start video.
    *   Our proxy intercepts this request and forces a local P2P connection.
    *   Video works locally without ever needing a cloud server.

## Uninstalling

To remove everything:
```bash
/etc/init.d/roborock-proxy disable
/etc/init.d/roborock-keepalive disable
# Manually remove rules from /etc/firewall.user
reboot
```
