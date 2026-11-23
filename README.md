# WAEC Practice Platform (Flask)

A Flask examination practice platform with authentication and subject/year CSV loading.

## Technology stack
- Python
- Flask
- SQLite
- Pandas
- python-dotenv
- OpenAI SDK

## Verified implementation
- Registers a Flask authentication blueprint
- creates a SQLite users table
- hashes passwords
- loads examination question data
- optionally initializes the OpenAI client.

## Getting started

```bash
git clone https://github.com/ebukaxyrus/waecflask.git
cd waecflask
python -m venv .venv
source .venv/bin/activate  # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

Review the source for required API credentials, data files, local environment settings, and device permissions before running. Never commit real API keys or passwords.

## Important limitations

Configure a strong SECRET_KEY and review authentication, error handling, dataset rights, and deployment security before public production use.

## Project structure

- `app.py`: primary application entry point.
- `requirements.txt`: Python package requirements.
- `auth.py`: registration/login implementation.
- `templates/`: HTML templates.
- `waec_data/`: structured examination datasets.

## Suggested next improvements

- [ ] Test installation from scratch and pin versions.
- [ ] Include real screenshots, verified live URL and a demo walkthrough.
- [ ] Add automated tests and document tested configuration.
- [ ] Verify source/data rights and operational security.

## Maintainer

**Dimakunne Chukwuebuka Francis**  
[GitHub](https://github.com/ebukaxyrus) · [Portfolio](https://xyrusportfolio.netlify.app/) · [XY AI Solution](https://xyaisolution.online/)

*Documentation is grounded in source review; the application was not independently deployed or benchmarked for this update.*
