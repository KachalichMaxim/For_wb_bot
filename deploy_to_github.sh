#!/bin/bash

# Script to push WB_tg_bot_supplies to GitHub and deploy to VM

REPO_NAME="WB_tg_bot_supplies"
GITHUB_USERNAME=""  # Replace with your GitHub username
VM_USER=""  # Replace with VM username
VM_HOST=""  # Replace with VM host/IP
SSH_KEY="/Users/kachalichmaxim/Desktop/Счета по ЦТС/ssh-key-1760689301227 2/ssh-key-1760689301227"

echo "=========================================="
echo "GitHub Repository Setup"
echo "=========================================="
echo ""
echo "Step 1: Create repository on GitHub"
echo "-----------------------------------"
echo "1. Go to https://github.com/new"
echo "2. Repository name: $REPO_NAME"
echo "3. Description: Wildberries Telegram Bot for supplies management"
echo "4. Set to Private (recommended for sensitive data)"
echo "5. DO NOT initialize with README, .gitignore, or license"
echo "6. Click 'Create repository'"
echo ""
echo "Step 2: Add remote and push"
echo "---------------------------"
read -p "Enter your GitHub username: " GITHUB_USERNAME
read -p "Press Enter after creating the repository on GitHub..."

# Add remote (update with your GitHub username)
git remote add origin "https://github.com/${GITHUB_USERNAME}/${REPO_NAME}.git" 2>/dev/null || \
git remote set-url origin "https://github.com/${GITHUB_USERNAME}/${REPO_NAME}.git"

# Push to GitHub
echo "Pushing to GitHub..."
git branch -M main
git push -u origin main

echo ""
echo "=========================================="
echo "VM Deployment"
echo "=========================================="
read -p "Enter VM username: " VM_USER
read -p "Enter VM host/IP: " VM_HOST

echo ""
echo "Connecting to VM and cloning repository..."
echo "Command: ssh -o StrictHostKeyChecking=no -i '$SSH_KEY' ${VM_USER}@${VM_HOST}"
echo ""

# Connect to VM and clone
ssh -o StrictHostKeyChecking=no -i "$SSH_KEY" ${VM_USER}@${VM_HOST} << EOF
cd ~
if [ -d "$REPO_NAME" ]; then
    echo "Repository already exists. Updating..."
    cd $REPO_NAME
    git pull
else
    echo "Cloning repository..."
    git clone https://github.com/${GITHUB_USERNAME}/${REPO_NAME}.git
    cd $REPO_NAME
fi

echo ""
echo "Repository ready at: ~/$REPO_NAME"
echo ""
echo "Next steps:"
echo "1. Copy .env file with your credentials"
echo "2. Install dependencies: pip3 install -r requirements.txt"
echo "3. Run the bot: python3 telegram_bot.py"
EOF

echo ""
echo "Done!"

