import discord
from discord.ext import commands # Import commands
import os
import asyncio
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from mcp_client import MCPClient
import json # For potentially parsing the result content

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
if not DISCORD_TOKEN:
    raise ValueError("DISCORD_TOKEN environment variable not set.")

# --- Configuration ---
MESSAGE_HISTORY_DURATION = timedelta(minutes=10) # Collect messages from the last 10 minutes
TARGET_REPO_OWNER = "jimmyhealer"
TARGET_REPO_NAME = "vocora"
COMMAND_PREFIX = "!" # Define command prefix
AUTO_DETECTION_ENABLED = True # Whether automatic issue detection is enabled
# --- End Configuration ---

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True # Ensure message content intent is enabled

# Use commands.Bot instead of discord.Client
client = commands.Bot(command_prefix=COMMAND_PREFIX, intents=intents)
mcp_client_instance = MCPClient() # Instantiate our MCPClient

# --- Helper Function ---
async def collect_recent_messages(channel: discord.TextChannel, duration: timedelta) -> list:
    """Collects recent messages from a channel, formatted for processing."""
    print(f"Collecting messages from the last {duration} in #{channel.name}...")
    history_limit_time = datetime.now(timezone.utc) - duration
    recent_messages_formatted = []
    raw_messages_content = [] # Store raw content for issue body

    try:
        async for msg in channel.history(limit=100, after=history_limit_time, oldest_first=True):
            # Format messages for the LLM (OpenAI format)
            role = "assistant" if msg.author == client.user else "user"
            user_name = str(msg.author.display_name or msg.author.name)
            formatted_content = f"{user_name}: {msg.content}"
            recent_messages_formatted.append({
                "role": role,
                "content": formatted_content
            })
            raw_messages_content.append(formatted_content) # Add raw formatted line to list
        print(f"Collected {len(recent_messages_formatted)} messages.")
        return recent_messages_formatted, "\n".join(raw_messages_content) # Return both formats
    except discord.Forbidden:
        print(f"Error: Missing permissions to read history in channel {channel.name}")
        await channel.send(f"Error: I don't have permissions to read message history in {channel.mention}.")
        return [], "" # Return empty lists on permission error
    except Exception as e:
        print(f"Error collecting message history in #{channel.name}: {e}")
        await channel.send("An error occurred while trying to fetch message history.")
        return [], "" # Return empty lists on other errors

# --- Bot Events ---
@client.event
async def on_ready():
    print(f'Logged in as {client.user}')
    print('Connecting to MCP server...')
    try:
        await mcp_client_instance.connect_to_server()
        print('MCP Client connected successfully.')
    except Exception as e:
        print(f'Failed to connect MCP client: {e}')
        # Optionally, you might want to shut down the bot if MCP connection fails
        # await client.close()

@client.event
async def on_message(message):
    # Ignore messages from the bot itself and commands
    if message.author == client.user or message.content.startswith(COMMAND_PREFIX):
        return

    # Only process messages in guilds (servers), not DMs
    if not message.guild:
        return

    print(f"\n[{datetime.now()}] Received message from {message.author} in #{message.channel}: {message.content}")

    # Skip automatic processing if disabled
    if not AUTO_DETECTION_ENABLED:
        print("Automatic issue detection is disabled. Skipping LLM processing.")
        # Still process commands
        await client.process_commands(message)
        return

    # Use the helper function to collect messages
    recent_messages_llm, _ = await collect_recent_messages(message.channel, MESSAGE_HISTORY_DURATION) # We only need LLM format here

    # Add the current message if it wasn't captured by history (due to timing)
    # Check based on raw content is difficult now, assume history captures it well enough for LLM trigger
    # Or, we can just always add it to the list sent to LLM if needed, checking for duplicates might be complex.
    # Let's simplify: Assume history + LLM is sufficient for auto-trigger.

    if not recent_messages_llm:
        print("No recent messages found to process for LLM.")
        return

    # Append the current message to ensure it's included in LLM context
    current_user_name = str(message.author.display_name or message.author.name)
    recent_messages_llm.append({
        "role": "user",
        "content": f"{current_user_name}: {message.content}"
    })


    # Send the conversation to the MCPClient for processing
    tool_call_result = await mcp_client_instance.process_conversation(recent_messages_llm)

    # Handle the result (if a tool was called by LLM)
    if tool_call_result:
        tool_name = tool_call_result.get("tool_name")
        arguments = tool_call_result.get("arguments", {})
        result_content = tool_call_result.get("result")
        error = tool_call_result.get("error")

        if error:
            reply_content = f"🚨 LLM tried to call `{tool_name}` but failed. Error: {error}"
            print(f"Error reported from MCPClient (LLM Call): {error}")
        elif tool_name == "create_issue":
            issue_url = "Unknown (Check MCP Server logs)"
            issue_title = arguments.get('title', '[No Title Provided]')
            try:
                # Parsing logic (same as before)
                if isinstance(result_content, str):
                    try:
                        result_data = json.loads(result_content)
                        if isinstance(result_data, dict):
                            issue_url = result_data.get("html_url", issue_url)
                    except json.JSONDecodeError:
                        if result_content.startswith('http'): issue_url = result_content
                elif isinstance(result_content, dict): issue_url = result_content.get("html_url", issue_url)
            except Exception as parse_err:
                print(f"Could not parse issue URL from result content (LLM Call): {parse_err}")
                print(f"Raw result content: {result_content}")

            reply_content = (
                f"✅ LLM decided to create a GitHub Issue: **{issue_title}**\n"
                f"🔗 Link: <{issue_url}>"
            )
            print(f"Issue created via LLM. URL: {issue_url}")
        else:
            reply_content = f"🛠️ LLM called tool `{tool_name}`. Result: `{result_content}`"
            print(f"Tool {tool_name} executed via LLM.")

        await message.reply(reply_content)
    else:
        print("No tool call was triggered by the LLM for the message.")

    # We need to process commands as well for the bot to respond to !issue
    await client.process_commands(message)


# --- Bot Commands ---
@client.command(name='issue')
async def create_manual_issue(ctx: commands.Context, *, issue_title: str = None):
    """Manually creates a GitHub issue from recent chat history."""
    print(f"\n[{datetime.now()}] Manual !issue command triggered by {ctx.author} in #{ctx.channel}")

    if not mcp_client_instance.session:
        await ctx.reply("🚨 Error: The connection to the GitHub MCP Server is not active. Cannot create issue.")
        return

    # Use helper to get messages (both formats)
    recent_messages_llm, messages_for_body = await collect_recent_messages(ctx.channel, MESSAGE_HISTORY_DURATION)

    if not messages_for_body:
        await ctx.reply("❌ Could not find any recent messages to include in the issue body.")
        return

    # Generate a title using LLM if none is provided
    final_issue_title = issue_title
    if not final_issue_title:
        # Let the user know we're generating a title
        await ctx.reply("🤔 Generating a suitable issue title based on the conversation...")
        
        try:
            # Add a system message to guide the LLM to generate a title
            title_generation_messages = [
                {
                    "role": "system", 
                    "content": "You are a helpful assistant that creates concise and descriptive GitHub issue titles. Based on the conversation provided, generate a short but informative title (max 80 characters) that summarizes the main problem or feature request discussed."
                }
            ]
            # Add the conversation history for context
            title_generation_messages.extend(recent_messages_llm)
            
            # Send to LLM for title generation, no tools needed for this
            chat_completion = mcp_client_instance.openai_client.chat.completions.create(
                model=mcp_client_instance.model_name,
                messages=title_generation_messages,
                max_tokens=50  # Short response for title
            )
            
            # Get the generated title
            generated_title = chat_completion.choices[0].message.content.strip()
            
            # Truncate if too long
            if len(generated_title) > 80:
                generated_title = generated_title[:77] + "..."
                
            final_issue_title = generated_title
            print(f"LLM generated title: '{final_issue_title}'")
            
        except Exception as e:
            print(f"Error generating title with LLM: {e}")
            # Fall back to default title if LLM fails
            final_issue_title = f"Manual Issue from Discord #{ctx.channel.name}"
            print(f"Using default title due to error: '{final_issue_title}'")
    
    # If we still don't have a title (very unlikely), use default
    if not final_issue_title:
        final_issue_title = f"Manual Issue from Discord #{ctx.channel.name}"

    # Prepare issue body
    issue_body = (
        f"Issue manually created by **{ctx.author.display_name}** using the `!issue` command.\n\n"
        f"**Relevant Conversation (last {MESSAGE_HISTORY_DURATION.total_seconds() / 60:.0f} minutes):**\n"
        f"```\n{messages_for_body}\n```"
    )

    tool_args = {
        "owner": TARGET_REPO_OWNER,
        "repo": TARGET_REPO_NAME,
        "title": final_issue_title,
        "body": issue_body
    }

    print(f"Attempting to directly call 'create_issue' via MCP:")
    print(f"- Arguments: {tool_args}")

    try:
        # Directly call the tool via MCP session, bypassing the LLM check
        result = await mcp_client_instance.session.call_tool("create_issue", tool_args)
        print(f"Tool 'create_issue' executed successfully (Manual Call).")
        result_content = result.content
        print(f"Tool Result Content: {result_content}")

        # Parse result for URL (similar logic)
        issue_url = "Unknown (Check MCP Server logs)"
        try:
            if isinstance(result_content, str):
                try:
                    result_data = json.loads(result_content)
                    if isinstance(result_data, dict): issue_url = result_data.get("html_url", issue_url)
                except json.JSONDecodeError:
                    if result_content.startswith('http'): issue_url = result_content
            elif isinstance(result_content, dict): issue_url = result_content.get("html_url", issue_url)
        except Exception as parse_err:
            print(f"Could not parse issue URL from result content (Manual Call): {parse_err}")

        reply_content = (
            f"✅ Manually created GitHub Issue: **{final_issue_title}**\n"
            f"🔗 Link: <{issue_url}>"
        )
        print(f"Manual issue created. URL: {issue_url}")

    except Exception as e:
        print(f"Error directly calling tool 'create_issue' via MCP: {e}")
        reply_content = f"🚨 Failed to manually create issue. Error: {e}"

    await ctx.reply(reply_content)

@client.command(name='autodetect')
async def toggle_auto_detection(ctx: commands.Context, setting: str = None):
    """Toggle automatic issue detection on/off or check current status."""
    global AUTO_DETECTION_ENABLED
    
    if setting is None:
        # Report current status
        status = "enabled" if AUTO_DETECTION_ENABLED else "disabled"
        await ctx.reply(f"🔍 Automatic issue detection is currently **{status}**.\nUse `!autodetect on` or `!autodetect off` to change.")
        return
    
    setting = setting.lower()
    if setting in ['on', 'enable', 'true', 'yes', '1']:
        AUTO_DETECTION_ENABLED = True
        await ctx.reply("✅ Automatic issue detection has been **enabled**. The bot will now monitor conversations for potential issues.")
    elif setting in ['off', 'disable', 'false', 'no', '0']:
        AUTO_DETECTION_ENABLED = False
        await ctx.reply("🛑 Automatic issue detection has been **disabled**. You can still create issues manually with `!issue`.")
    else:
        await ctx.reply("❓ Invalid setting. Please use `on` or `off` (e.g., `!autodetect on`).")
    
    print(f"[{datetime.now()}] Automatic issue detection set to: {AUTO_DETECTION_ENABLED} by {ctx.author}")

# --- Main Execution ---
async def main():
    async with client:
        try:
            print("Starting Discord bot...")
            await client.start(DISCORD_TOKEN)
        except discord.LoginFailure:
            print("Error: Invalid Discord Token. Please check your .env file.")
        except Exception as e:
            print(f"Error starting Discord bot: {e}")
        finally:
            print("Cleaning up MCP client...")
            await mcp_client_instance.cleanup()
            print("Bot shutdown complete.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot stopped manually.")
 