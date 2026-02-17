#!/bin/sh
# Roborock offline kit - installer
# Works on OpenWRT / GL.iNet routers

REPO_URL="https://raw.githubusercontent.com/serphen/roborock-offline/main"
INSTALL_DIR="/usr/share/roborock-offline"
CONF_FILE="/etc/roborock.conf"
SERVICE_PROXY="roborock-proxy"
SERVICE_KEEPALIVE="roborock-keepalive"

echo "=============================================="
echo "   Roborock offline kit - installer"
echo "=============================================="

# 1. Check internet
ping -c 1 8.8.8.8 > /dev/null 2>&1
if [ $? -ne 0 ]; then
    echo "Error: no internet connection."
    echo "Please connect your router WAN port to internet for installation."
    exit 1
fi

# 2. Update OPKG & Install Python
echo "Installing Python3 and dependencies..."
opkg update
opkg install python3 python3-pip python3-asyncio

# 3. Install Python Libraries
echo "Installing Python libraries (python-roborock)..."
pip3 install python-roborock

# 4. Create Installation Directory
mkdir -p $INSTALL_DIR

# 5. Download Scripts
echo "Downloading scripts..."
wget -O $INSTALL_DIR/roborock_mitm_proxy.py "$REPO_URL/roborock_mitm_proxy.py"
wget -O $INSTALL_DIR/roborock_keepalive_server.py "$REPO_URL/roborock_keepalive_server.py"
wget -O $INSTALL_DIR/get_key.py "$REPO_URL/get_key.py"

chmod +x $INSTALL_DIR/*.py

# 6. Configuration Management (Cache)
EXISTING_KEY=""
if [ -f $CONF_FILE ]; then
    . $CONF_FILE
    if [ ! -z "$ROBOROCK_KEY" ]; then
        EXISTING_KEY="$ROBOROCK_KEY"
    fi
fi

USE_EXISTING="n"
if [ ! -z "$EXISTING_KEY" ]; then
    echo ""
    echo "Existing configuration found."
    echo "Key: ${EXISTING_KEY:0:5}......${EXISTING_KEY: -5}"
    echo -n "Use this key? [Y/n]: "
    read USE_EXISTING
    USE_EXISTING=${USE_EXISTING:-y} # Default Yes
fi

if [ "$USE_EXISTING" = "y" ] || [ "$USE_EXISTING" = "Y" ]; then
    echo "Using existing key."
else
    echo ""
    echo "Fetching new key..."
    python3 $INSTALL_DIR/get_key.py
    
    if [ ! -f /tmp/roborock_key.env ]; then
        echo "Setup aborted."
        exit 1
    fi
    
    # Load and Save new key
    . /tmp/roborock_key.env
    echo "ROBOROCK_KEY='$ROBOROCK_KEY'" > $CONF_FILE
    echo "ROBOROCK_DUID='$ROBOROCK_DUID'" >> $CONF_FILE
    echo "ROBOROCK_NAME='$ROBOROCK_NAME'" >> $CONF_FILE
    rm /tmp/roborock_key.env
fi

# Reload config to be sure
. $CONF_FILE

if [ -z "$ROBOROCK_KEY" ]; then
    echo "Error: no key defined."
    exit 1
fi

# 7. Create Services (init.d)

# --- Service Proxy ---
cat << EOF > /etc/init.d/$SERVICE_PROXY
#!/bin/sh /etc/rc.common

START=99
STOP=10
USE_PROCD=1

SCRIPT="$INSTALL_DIR/roborock_mitm_proxy.py"
PROG=/usr/bin/python3
CONF="/etc/roborock.conf"

start_service() {
    if [ -f \$CONF ]; then
        . \$CONF
    fi
    
    if [ -z "\$ROBOROCK_KEY" ]; then
        echo "No key found in \$CONF"
        exit 1
    fi

    procd_open_instance
    procd_set_param command \$PROG \$SCRIPT
    procd_set_param env ROBOROCK_LOCAL_KEY="\$ROBOROCK_KEY"
    procd_set_param stdout 1
    procd_set_param stderr 1
    procd_set_param respawn
    procd_close_instance
}
EOF
chmod +x /etc/init.d/$SERVICE_PROXY

# --- Service KeepAlive ---
cat << EOF > /etc/init.d/$SERVICE_KEEPALIVE
#!/bin/sh /etc/rc.common

START=99
STOP=10
USE_PROCD=1

SCRIPT="$INSTALL_DIR/roborock_keepalive_server.py"
PROG=/usr/bin/python3

start_service() {
    procd_open_instance
    procd_set_param command \$PROG \$SCRIPT
    procd_set_param stdout 1
    procd_set_param stderr 1
    procd_set_param respawn
    procd_close_instance
}
EOF
chmod +x /etc/init.d/$SERVICE_KEEPALIVE

# 8. Configure Firewall
echo "Configuring firewall..."
sed -i '/roborock-offline/d' /etc/firewall.user
cat << EOF >> /etc/firewall.user
# -- roborock-offline start --
iptables -t nat -A PREROUTING -p tcp --dport 58867 -j REDIRECT --to-ports 58867
iptables -t nat -A PREROUTING -p udp --dport 8053 -j REDIRECT --to-ports 8053
iptables -t nat -A PREROUTING -p tcp --dport 8053 -j REDIRECT --to-ports 8053
# -- roborock-offline end --
EOF
/etc/init.d/firewall restart

# 9. Enable & Start
echo "Starting services..."
/etc/init.d/$SERVICE_PROXY enable
/etc/init.d/$SERVICE_PROXY restart
/etc/init.d/$SERVICE_KEEPALIVE enable
/etc/init.d/$SERVICE_KEEPALIVE restart

echo ""
echo "Installation complete."
echo "1. Disconnect WAN."
echo "2. Connect robot."
echo "3. Enjoy."
