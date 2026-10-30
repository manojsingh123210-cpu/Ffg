import os
import threading
import asyncio

# Render → PORT env automatically set karta hai
os.environ["WEB_PORT"] = os.environ.get("PORT", "5000")

def run_bot():
    from bot import main as bot_main
    asyncio.run(bot_main())

if __name__ == "__main__":
    t = threading.Thread(target=run_bot, daemon=True)
    t.start()
    from web import app
    port = int(os.environ.get("PORT", 5000))
    print(f"🌐 Web on :{port}")
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
