from dotenv import load_dotenv

from app import create_app

load_dotenv()

app = create_app()

if __name__ == "__main__":
    import os
    from threading import Thread

    from app.notifications import watch_reminders
    from app.source_scheduler import watch_sources

    if not app.debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        Thread(target=watch_sources, args=(app,), daemon=True).start()
        Thread(target=watch_reminders, args=(app,), daemon=True).start()
    app.run(host="127.0.0.1", port=5000, debug=app.debug)
