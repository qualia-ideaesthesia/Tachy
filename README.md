# Tachy

**An Arcaea Discord bot for B50 generation, personalized chart recommendations, and account management.**

Tachy connects your Discord account to an Arcaea account and provides tools to review your performance, discover charts to practice, and manage account settings.

## Features

### Best 50 Generation

Generate a visual representation of your Best 50 (B50) records.

- Fetches the player's best records from the Arcaea server API.
- Displays song jackets, chart constants, scores, and play ratings.
- Uses difficulty-specific colors to distinguish chart levels.
- Includes the player's username and potential (PTT) in the Discord embed.

### Personalized Chart Recommendations

Get three charts selected for your current skill level.

Tachy analyzes your B50 records, recent plays (R30), and official PTT to build a player profile and estimate suitable chart constants.

Recommendations are divided into three categories:

| Category | Purpose |
|----------|---------|
| Warm-up | A relatively comfortable chart to get started. |
| Base | A chart around your estimated training level. |
| Challenge | A chart intended to push your current limits. |

The recommendation pipeline combines statistical analysis, candidate filtering, and an OpenAI-compatible LLM endpoint to select suitable charts from the available candidates.

Song metadata and chart constants are retrieved from the song list and server database rather than invented by the LLM.

### Account Linking

Link a Discord account to an existing Arcaea account using its username.

The association is stored locally in a separate SQLite database, allowing users to access their records without entering their username every time.

### Memory Management

Update the linked Arcaea account's memory value through a Discord slash command.

### Latency Check

Check the bot's Discord gateway latency and response time.

## Commands

| Command | Description |
|---------|-------------|
| `/link <username>` | Link your Discord account to an Arcaea account. |
| `/b50` | Generate an image of your Best 50 records. |
| `/recommendations` | Get three personalized chart recommendations. |
| `/changemem <memory>` | Change the linked account's memory value. |
| `/ping` | Check the bot's latency. |

Account-specific commands require a linked Arcaea account.

## Requirements

- Python 3.10 or newer
- A Discord application and bot token
- An accessible Arcaea server exposing the API endpoints used by Tachy
- Access to the server's SQLite database
- A compatible song list JSON file
- Album jacket assets (optional, but recommended)
- An OpenAI-compatible API endpoint for chart recommendations

The recommendation feature requires an LLM service. The B50 generation and account management features do not use the LLM endpoint.

## Installation

Clone the repository:

```bash
git clone <repository-url>
cd Tachy