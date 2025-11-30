# GitHub Repository Setup Instructions

## Step 1: Create Repository on GitHub

1. Go to https://github.com/new
2. Repository name: `WB_tg_bot_supplies`
3. Description: `Wildberries Telegram Bot for supplies management`
4. Set to **Private** (recommended - contains sensitive data like API keys)
5. **DO NOT** check "Initialize this repository with README"
6. Click **Create repository**

## Step 2: Push Code to GitHub

After creating the repository, run these commands (replace `YOUR_GITHUB_USERNAME`):

```bash
cd /Users/kachalichmaxim/Desktop/WB_tg_bot_supplies

# Add remote (replace YOUR_GITHUB_USERNAME)
git remote add origin https://github.com/YOUR_GITHUB_USERNAME/WB_tg_bot_supplies.git

# Ensure we're on main branch
git branch -M main

# Push to GitHub
git push -u origin main
```

## Step 3: Deploy to VM

After pushing to GitHub, connect to your VM and clone:

```bash
# Replace VM_USER and VM_HOST with your actual values
cd /Users/kachalichmaxim/Desktop/gg_bot_for_edu

ssh -o StrictHostKeyChecking=no -i '/Users/kachalichmaxim/Desktop/Счета по ЦТС/ssh-key-1760689301227 2/ssh-key-1760689301227' VM_USER@VM_HOST

# On VM, clone the repository:
cd ~
git clone https://github.com/YOUR_GITHUB_USERNAME/WB_tg_bot_supplies.git
cd WB_tg_bot_supplies

# Setup and run:
pip3 install -r requirements.txt
# Copy your .env file
nohup python3 telegram_bot.py > bot.log 2>&1 &
```

## Quick Commands Reference

### Push to GitHub
```bash
git remote add origin https://github.com/YOUR_GITHUB_USERNAME/WB_tg_bot_supplies.git
git branch -M main
git push -u origin main
```

### Connect to VM
```bash
ssh -o StrictHostKeyChecking=no -i '/Users/kachalichmaxim/Desktop/Счета по ЦТС/ssh-key-1760689301227 2/ssh-key-1760689301227' VM_USER@VM_HOST
```

