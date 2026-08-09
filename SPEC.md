# Activity Telemetry

## Local Python client/script
- track number of
    - left clicks
    - right clicks
    - mouse movement in meters
- track count of different keys pressed (focus on mac qwerty keyboard layout)

- track application time, whitelist of applications
    - Anki
    - Notion
    - Obsidian
    - Valorant
    - Google Chrome
    - Visual Studio Code
    - Ghostty

- data written directly from client to MongoDB Atlas database

## Next.js frontend
- personal website main page
    - render mouse with hoverable left / right button components, displaying corresponding statistics
    - render macbook QWERTY layout keyboard, with heatmap of different keys pressed
