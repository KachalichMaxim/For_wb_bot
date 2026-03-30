#!/bin/bash
# Deployment script for Wildberries Telegram Bot on VM (using password authentication)

SSH_USER='root'
SSH_HOST='45.159.248.211'
SSH_PASS='LDne17ikUS34'
REPO_URL='https://github.com/KachalichMaxim/For_wb_bot.git'
PROJECT_DIR='~/For_wb_bot'
LOCAL_PROJECT_DIR='/Users/kachalichmaxim/Desktop/WB_tg_bot_supplies'

echo "🚀 Starting deployment to VM..."

# Check if sshpass is installed
if ! command -v sshpass &> /dev/null; then
    echo "⚠️  sshpass is not installed. Installing..."
    if [[ "$OSTYPE" == "darwin"* ]]; then
        if ! command -v brew &> /dev/null; then
            echo "❌ Please install Homebrew first: /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
            exit 1
        fi
        brew install hudochenkov/sshpass/sshpass
    else
        echo "Please install sshpass: sudo apt-get install sshpass (Ubuntu/Debian) or sudo yum install sshpass (CentOS/RHEL)"
        exit 1
    fi
fi

# Step 1: Connect to VM and clone/update repository
echo "📦 Cloning/updating repository on VM..."
sshpass -p "$SSH_PASS" ssh -o StrictHostKeyChecking=no ${SSH_USER}@${SSH_HOST} << 'ENDSSH'
    if [ -d ~/For_wb_bot ]; then
        echo 'Repository exists, updating...'
        cd ~/For_wb_bot
        git pull origin main
    else
        echo 'Repository does not exist, cloning...'
        cd ~
        git clone https://github.com/KachalichMaxim/For_wb_bot.git
        cd ~/For_wb_bot
    fi
ENDSSH

# Step 2: Upload .env file
if [ -f "${LOCAL_PROJECT_DIR}/.env" ]; then
    echo "📤 Uploading .env file..."
    sshpass -p "$SSH_PASS" scp -o StrictHostKeyChecking=no \
        "${LOCAL_PROJECT_DIR}/.env" \
        ${SSH_USER}@${SSH_HOST}:~/For_wb_bot/.env
else
    echo "⚠️  .env file not found locally. Please create it on VM manually."
fi

# Step 3: Upload Google Service Account JSON file
if [ -f "${LOCAL_PROJECT_DIR}/tonal-concord-464913-u3-2024741e839c.json" ]; then
    echo "📤 Uploading Google Service Account JSON..."
    sshpass -p "$SSH_PASS" scp -o StrictHostKeyChecking=no \
        "${LOCAL_PROJECT_DIR}/tonal-concord-464913-u3-2024741e839c.json" \
        ${SSH_USER}@${SSH_HOST}:~/For_wb_bot/
else
    echo "⚠️  JSON file not found. Please upload it manually."
fi

# Step 4: Install dependencies and setup on VM
echo "⚙️  Setting up environment on VM..."
sshpass -p "$SSH_PASS" ssh -o StrictHostKeyChecking=no ${SSH_USER}@${SSH_HOST} << 'ENDSSH'
    cd ~/For_wb_bot
    
    # Update system packages
    echo "Updating system packages..."
    apt-get update -qq
    
    # Install Python 3 and pip if not installed
    if ! command -v python3 &> /dev/null; then
        echo "Installing Python 3..."
        apt-get install -y python3 python3-pip python3-venv
    fi
    
    # Create virtual environment if it doesn't exist
    if [ ! -d venv ]; then
        echo 'Creating virtual environment...'
        python3 -m venv venv
    fi
    
    # Activate venv and install dependencies
    source venv/bin/activate
    pip install --upgrade pip -q
    pip install -r requirements.txt
    
    echo '✅ Setup completed!'
ENDSSH

# Step 5: Create systemd service for auto-start
echo "🔧 Creating systemd service..."
sshpass -p "$SSH_PASS" ssh -o StrictHostKeyChecking=no ${SSH_USER}@${SSH_HOST} << 'ENDSSH'
    cd ~/For_wb_bot
    
    # Create systemd service file
    cat > /tmp/wb_bot.service << 'EOFSERVICE'
[Unit]
Description=Wildberries Telegram Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/For_wb_bot
Environment="PATH=/root/For_wb_bot/venv/bin"
ExecStart=/root/For_wb_bot/venv/bin/python3 /root/For_wb_bot/telegram_bot.py
Restart=always
RestartSec=10
StandardOutput=append:/root/For_wb_bot/bot.log
StandardError=append:/root/For_wb_bot/bot.log

[Install]
WantedBy=multi-user.target
EOFSERVICE
    
    # Copy service file to systemd directory
    sudo cp /tmp/wb_bot.service /etc/systemd/system/wb_bot.service
    sudo systemctl daemon-reload
    sudo systemctl enable wb_bot.service
    
    echo '✅ Systemd service created and enabled!'
ENDSSH

echo ""
echo "✅ Deployment completed!"
echo ""
echo "To start the bot:"
echo "  sshpass -p '$SSH_PASS' ssh -o StrictHostKeyChecking=no ${SSH_USER}@${SSH_HOST} 'sudo systemctl start wb_bot'"
echo ""
echo "To check status:"
echo "  sshpass -p '$SSH_PASS' ssh -o StrictHostKeyChecking=no ${SSH_USER}@${SSH_HOST} 'sudo systemctl status wb_bot'"
echo ""
echo "To view logs:"
echo "  sshpass -p '$SSH_PASS' ssh -o StrictHostKeyChecking=no ${SSH_USER}@${SSH_HOST} 'tail -f ~/For_wb_bot/bot.log'"
echo ""
echo "To stop the bot:"
echo "  sshpass -p '$SSH_PASS' ssh -o StrictHostKeyChecking=no ${SSH_USER}@${SSH_HOST} 'sudo systemctl stop wb_bot'"


