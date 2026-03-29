# Deploy to VM Instructions

## Repository URL
- GitHub: https://github.com/KachalichMaxim/For_wb_bot.git
- SSH: git@github.com:KachalichMaxim/For_wb_bot.git

## Step 1: Connect to VM

```bash
cd /Users/kachalichmaxim/Desktop/gg_bot_for_edu

# Replace VM_USER and VM_HOST with your actual values
ssh -o StrictHostKeyChecking=no -i '/Users/kachalichmaxim/Desktop/Счета по ЦТС/ssh-key-1760689301227 2/ssh-key-1760689301227' VM_USER@VM_HOST
```

## Step 2: Clone Repository on VM

Once connected to VM:

```bash
cd ~

# Clone the repository
git clone https://github.com/KachalichMaxim/For_wb_bot.git
cd For_wb_bot
```

## Step 3: Setup Environment

```bash
# Install Python dependencies
pip3 install -r requirements.txt

# Create .env file with your credentials
nano .env
# Or use your preferred editor to create .env with:
# TELEGRAM_BOT_TOKEN=your_token
# GOOGLE_SHEETS_ID=your_sheets_id
# GOOGLE_SERVICE_ACCOUNT_JSON=path_to_json
# LOG_LEVEL=INFO
# LOG_FILE=bot.log

# Copy service account JSON file to VM (from local machine)
# You'll need to copy tonal-concord-464913-u3-2024741e839c.json manually
```

## Step 4: Run the Bot

```bash
# Run in background
nohup python3 telegram_bot.py > bot.log 2>&1 &

# Check if it's running
ps aux | grep telegram_bot

# View logs
tail -f bot.log
```

## Quick Commands

### Connect to VM
```bash
cd /Users/kachalichmaxim/Desktop/gg_bot_for_edu
ssh -o StrictHostKeyChecking=no -i '/Users/kachalichmaxim/Desktop/Счета по ЦТС/ssh-key-1760689301227 2/ssh-key-1760689301227' VM_USER@VM_HOST
```

### On VM - Clone and Setup
```bash
cd ~ && git clone https://github.com/KachalichMaxim/For_wb_bot.git
cd For_wb_bot && pip3 install -r requirements.txt
```

### Run Bot
```bash
nohup python3 telegram_bot.py > bot.log 2>&1 &
```

