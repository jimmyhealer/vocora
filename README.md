# MCP Discord Bot

An intelligent Discord Bot that monitors developer conversations and automatically or manually creates GitHub Issues.

## 📚 Project Overview

This Discord Bot uses OpenRouter's Quasar Alpha model and GitHub MCP Tool Server to implement the following features:

1. **Automatic Issue Detection**: The bot collects recent conversations in Discord channels and uses LLM to determine if a GitHub Issue needs to be created.
2. **Manual Issue Creation**: Use the `!issue [title]` command to directly create a GitHub Issue containing recent conversations.
3. **AI-Generated Titles**: When no title is provided with the `!issue` command, the LLM automatically generates a relevant title based on the conversation.
4. **Real-time Feedback**: After creating an issue, it provides the Issue link in the Discord channel.

## 🔧 System Architecture

```
[Discord Channel Chat] <----> [Discord Bot] <----> [LLM (Quasar Alpha)]
                                  |
                                  v
                       [GitHub MCP Tool Server]
                                  |
                                  v
                           [GitHub Issues]
```

## 🚀 Installation & Setup

### Prerequisites

- Python 3.8+
- Discord Bot Token
- OpenRouter API Key
- GitHub MCP Tool Server

### Installation Steps

1. **Clone the project**

```bash
git clone https://github.com/yourusername/mcp-discord-bot.git
cd mcp-discord-bot
```

2. **Install dependencies**

```bash
pip install -r requirements.txt
```

3. **Environment Configuration**

Create a `.env` file and fill in the following information:

```env
DISCORD_TOKEN=your_Discord_Bot_Token
OPENROUTER_API_KEY=your_OpenRouter_API_Key
GITHUB_PERSONAL_ACCESS_TOKEN=GitHub_Personal_Access_Token
```

4. **Configure Discord Bot Permissions**

In the [Discord Developer Portal](https://discord.com/developers/applications):
- Enable "Message Content Intent"
- Set appropriate Bot permissions (read messages, send messages, etc.)

## 💻 Usage

### Starting the Bot

```bash
python bot.py
```

### Automatic Monitoring

The bot automatically monitors conversations in the channel and creates GitHub Issues when it detects topics that need tracking.

### Manual Commands

- `!issue` - Creates a GitHub Issue with an AI-generated title based on the conversation content
- `!issue Custom Title` - Creates a GitHub Issue with your specified title
- `!autodetect` - Shows the current status of automatic issue detection
- `!autodetect on/off` - Enables or disables automatic issue detection

Both `!issue` commands include conversations from the last 10 minutes in the issue body. When automatic detection is disabled, the bot will only create issues when explicitly commanded with `!issue`.

## 🔐 Core Module Description

### 1. Discord Bot (`bot.py`)

Responsible for receiving Discord messages, executing command processing, and interacting with the MCP Client.

Main features:
- Monitor channel messages
- Collect recent conversation history
- Process `!issue` commands with AI-generated titles
- Reply with Issue creation results

### 2. MCP Client (`mcp_client.py`)

Responsible for interacting with OpenRouter's LLM and GitHub MCP Tool Server.

Main features:
- Connect to GitHub MCP service
- Send conversations to LLM for analysis
- Generate issue titles automatically
- Execute `create_issue` tool calls
- Handle results and errors

## 🧩 Custom Configuration

Adjustable settings in the `bot.py` file:

```python
# Time range for collecting message history
MESSAGE_HISTORY_DURATION = timedelta(minutes=10)

# Target GitHub repository
TARGET_REPO_OWNER = "jimmyhealer"
TARGET_REPO_NAME = "vocora"

# Command prefix
COMMAND_PREFIX = "!"

# Automatic issue detection (can be toggled with !autodetect command)
AUTO_DETECTION_ENABLED = True
```

## 🔍 Troubleshooting

### Connection Issues

- **MCP server connection failure** - Verify the `MCP_GITHUB_SERVER_PATH` path is correct
- **Discord connection failure** - Check Discord Token and bot permissions
- **LLM response error** - Confirm OpenRouter API key and available quota

### Permission Issues

- **Cannot read message history** - Ensure Bot has `READ_MESSAGE_HISTORY` permission
- **Cannot send messages** - Ensure Bot has `SEND_MESSAGES` permission

## 📋 References

- [GitHub MCP Tool Server](https://github.com/github/github-mcp-server)
- [OpenRouter](https://openrouter.ai/)
- [Quasar Alpha](https://openrouter.ai/models/openrouter/quasar-alpha)
- [Discord.py Documentation](https://discordpy.readthedocs.io/) 