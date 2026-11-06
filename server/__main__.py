from server.app import build_production_app

app = build_production_app()


def main() -> None:
    import os

    port = int(os.environ.get("PORT", "3000"))
    print(f"AI Support Agent running at http://127.0.0.1:{port}")
    app.run(host="127.0.0.1", port=port, debug=False)


if __name__ == "__main__":
    main()
