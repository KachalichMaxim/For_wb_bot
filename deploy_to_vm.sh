#!/bin/bash
# Deployment script for Wildberries Telegram Bot on VM

SSH_KEY='/Users/kachalichmaxim/Desktop/Счета по ЦТС/ssh-key-1760689301227 2/ssh-key-1760689301227'
SSH_USER='bookntrack'
SSH_HOST='89.169.173.221'
REPO_URL='https://github.com/KachalichMaxim/For_wb_bot.git'
PROJECT_DIR='~/For_wb_bot'
LOCAL_PROJECT_DIR='/Users/kachalichmaxim/Desktop/WB_tg_bot_supplies'

echo "🚀 Starting deployment to VM..."

# Step 1: Connect to VM and clone/update repository
echo "📦 Cloning/updating repository on VM..."
ssh -o StrictHostKeyChecking=no -i "$SSH_KEY" ${SSH_USER}@${SSH_HOST} "
    if [ -d ${PROJECT_DIR} ]; then
        echo 'Repository exists, updating...'
        cd ${PROJECT_DIR}
        git pull origin main
    else
        echo 'Repository does not exist, cloning...'
        cd ~
        git clone ${REPO_URL} For_wb_bot
        cd ${PROJECT_DIR}
    fi
"

# Step 2: Upload .env file (if it exists locally)
if [ -f "${LOCAL_PROJECT_DIR}/.env" ]; then
    echo "📤 Uploading .env file..."
    scp -o StrictHostKeyChecking=no -i "$SSH_KEY" \
        "${LOCAL_PROJECT_DIR}/.env" \
        ${SSH_USER}@${SSH_HOST}:${PROJECT_DIR}/.env
else
    echo "⚠️  .env file not found locally. Please create it on VM manually."
fi

# Step 3: Upload Google Service Account JSON file
if [ -f "${LOCAL_PROJECT_DIR}/tonal-concord-464913-u3-2024741e839c.json" ]; then
    echo "📤 Uploading Google Service Account JSON..."
    scp -o StrictHostKeyChecking=no -i "$SSH_KEY" \
        "${LOCAL_PROJECT_DIR}/tonal-concord-464913-u3-2024741e839c.json" \
        ${SSH_USER}@${SSH_HOST}:${PROJECT_DIR}/
else
    echo "⚠️  JSON file not found. Please upload it manually."
fi

# Step 4: Install dependencies and setup on VM
echo "⚙️  Setting up environment on VM..."
ssh -o StrictHostKeyChecking=no -i "$SSH_KEY" ${SSH_USER}@${SSH_HOST} "
    cd ${PROJECT_DIR}
    
    # Create virtual environment if it doesn't exist
    if [ ! -d venv ]; then
        echo 'Creating virtual environment...'
        python3 -m venv venv
    fi
    
    # Activate venv and install dependencies
    source venv/bin/activate
    pip install --upgrade pip
    pip install -r requirements.txt
    
    echo '✅ Setup completed!'
"

echo "✅ Deployment preparation completed!"
echo ""
echo "To start the bot, run:"
echo "ssh -o StrictHostKeyChecking=no -i '$SSH_KEY' ${SSH_USER}@${SSH_HOST} 'cd ${PROJECT_DIR} && source venv/bin/activate && python3 max_bot.py'"
echo ""
echo "Or to run in background with screen:"
echo "ssh -o StrictHostKeyChecking=no -i '$SSH_KEY' ${SSH_USER}@${SSH_HOST} 'cd ${PROJECT_DIR} && screen -dmS wb_bot bash -c \"source venv/bin/activate && python3 max_bot.py\"'"
echo ""
echo "To view logs:"
echo "ssh -o StrictHostKeyChecking=no -i '$SSH_KEY' ${SSH_USER}@${SSH_HOST} 'cd ${PROJECT_DIR} && tail -f bot.log'"

