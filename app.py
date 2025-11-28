import os
import re
from pathlib import Path
from flask import (
    Flask, render_template, request, redirect, url_for, session,
    send_from_directory, flash, Response
)
import pandas as pd
from gtts import gTTS
from dotenv import load_dotenv
import requests

# Optional OpenAI client import
try:
    from openai import OpenAI as OpenAIClient
    OPENAI_CLIENT_AVAILABLE = True
except Exception:
    OPENAI_CLIENT_AVAILABLE = False

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'dev-secret')

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / 'waec_data'
STATIC_AUDIO = BASE_DIR / 'static' / 'audio'
STATIC_AUDIO.mkdir(parents=True, exist_ok=True)

OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
client = None
if OPENAI_API_KEY and OPENAI_CLIENT_AVAILABLE:
    try:
        client = OpenAIClient(api_key=OPENAI_API_KEY)
    except Exception:
        client = None


# ---------------- Helper Functions ----------------

def format_question_text(text):
    """Convert markdown-style text to HTML."""
    if pd.isna(text) or not text:
        return ""
    text = str(text).strip()
    text = re.sub(r'_([^_]+)_', r'<u>\1</u>', text)
    text = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'\*([^*]+)\*', r'<em>\1</em>', text)
    return text


def clean_option_text(text):
    """Clean and normalize options."""
    if pd.isna(text) or not text:
        return "Option missing"
    text = str(text).strip()
    text = re.sub(r'^[A-D]\.\s*', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text


def load_data(subject: str, year: int):
    """Load a WAEC dataset dynamically based on subject and year."""
    filename = DATA_DIR / f"waec_{subject}_{year}_complete.csv"
    if not filename.exists():
        raise FileNotFoundError(f"File not found: {filename}")

    df = pd.read_csv(filename)
    if df.empty:
        raise ValueError("CSV file is empty")

    required = [
        "Question", "OptionA", "OptionB", "OptionC", "OptionD",
        "Answer", "Question_Number", "Question_Type"
    ]
    for col in required:
        if col not in df.columns:
            raise ValueError(f"Missing required column: {col}")

    if "Image_URLs" not in df.columns:
        df["Image_URLs"] = ""

    df_filtered = df.dropna(subset=["Question", "Answer"])
    df_filtered["Image_URLs_List"] = df_filtered["Image_URLs"].apply(
        lambda x: re.split(r'[|,]', str(x)) if pd.notna(x) and str(x).strip() else []
    )
    df_filtered["Image_URLs_List"] = df_filtered["Image_URLs_List"].apply(
        lambda urls: [u.strip() for u in urls if u.strip()]
    )
    # Only keep the first valid image per question
    df_filtered["Image_URLs_List"] = df_filtered["Image_URLs_List"].apply(
        lambda urls: urls[:1] if urls else []
    )



    return df_filtered.reset_index(drop=True)


def generate_audio_gtts(text: str, filepath: Path, lang='en') -> Path:
    """Generate MP3 from text."""
    if not text or text.strip() == "":
        return None
    tts = gTTS(text)
    tts.save(str(filepath))
    return filepath


def generate_explanation(idx, year, subject, q, selected, correct):
    """Generate AI explanation using GPT."""
    if not client:
        return "AI explanation unavailable (missing API key)."

    try:
        prompt = (
            f"Explain briefly (2–3 sentences) why option {correct} is correct "
            f"for this WAEC {subject.title()} question:\n\n{q['Question']}\n\n"
            f"A. {q['OptionA']}\nB. {q['OptionB']}\nC. {q['OptionC']}\nD. {q['OptionD']}\n\n"
        )
        if selected != correct:
            prompt += f"The student chose {selected}. Explain why that is incorrect.\n"

        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a helpful WAEC tutor. Keep answers short and clear."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.5,
            max_tokens=120
        )

        explanation = completion.choices[0].message.content.strip()

        audio_path = STATIC_AUDIO / f"explanation_{subject}_{idx}_{year}.mp3"
        if not audio_path.exists():
            generate_audio_gtts(explanation, audio_path)

        return explanation
    except Exception as e:
        return f"⚠️ Error generating explanation: {e}"


def init_session_state(subject, year):
    """Initialize quiz session."""
    session['subject'] = subject
    session['year'] = year
    session['index'] = 0
    session['score'] = 0
    session['attempted'] = {}
    session['show_explanation'] = False
    session['explanations'] = {}


# ---------------- Routes ----------------

@app.route('/')
def index():
    years = list(range(2024, 2014, -1))
    return render_template('index.html', years=years)


@app.route('/start', methods=['POST'])
def start():
    subject = request.form.get('subject', 'english')
    year = int(request.form.get('year', 2024))
    session.clear()

    try:
        load_data(subject, year)
    except Exception as e:
        flash(str(e), 'danger')
        return redirect(url_for('index'))

    init_session_state(subject, year)
    flash(f"🎓 Starting {subject.title()} quiz for {year}", "info")
    return redirect(url_for('quiz'))


@app.route('/quiz')
def quiz():
    subject = session.get('subject', 'english')
    year = session.get('year', 2024)

    df = load_data(subject, year)
    idx = int(session.get('index', 0))
    if idx < 0 or idx >= len(df):
        idx = 0
        session['index'] = 0

    q = df.iloc[idx].copy()
    q['Question'] = format_question_text(q['Question'])

    options = {}
    display_opts = {}
    for opt in ['A', 'B', 'C', 'D']:
        val = clean_option_text(q[f"Option{opt}"])
        options[opt] = val
        display_opts[opt] = f"{opt}. {val}"

    attempted = session.get('attempted', {})
    stored_answer = attempted.get(str(idx))
    skipped_count = len([v for v in attempted.values() if v == 'SKIPPED'])
    attempted_for_score = [v for v in attempted.values() if v != 'SKIPPED']
    accuracy = (session.get('score', 0) / len(attempted_for_score)) * 100 if attempted_for_score else 0
    progress = (idx + 1) / len(df) * 100

    return render_template(
        'question.html',
        q=q, idx=idx, subject=subject, year=year, options=options,
        display_opts=display_opts, stored_answer=stored_answer,
        score=session.get('score', 0), accuracy=accuracy,
        progress=progress, skipped_count=skipped_count, total=len(df)
    )


@app.route('/action', methods=['POST'])
def action():
    act = request.form.get('action')
    subject = session.get('subject', 'english')
    year = session.get('year', 2024)
    df = load_data(subject, year)
    idx = int(session.get('index', 0))
    q = df.iloc[idx]

    if act == 'submit':
        selected = request.form.get('selected')
        if not selected:
            flash("Please select an option before submitting.", "warning")
            return redirect(url_for('quiz'))

        correct = str(q['Answer']).strip().upper()
        attempted = session.get('attempted', {})

        # ✅ Only score the first time a question is answered
        if str(idx) not in attempted:
            attempted[str(idx)] = selected
            if selected == correct:
                session['score'] = session.get('score', 0) + 1
                flash(f"✅ Correct! ({selected})", "success")
            else:
                flash(f"❌ Incorrect! You chose {selected}, correct is {correct}.", "danger")
        else:
            flash("⚠️ You already answered this question.", "info")

        session['attempted'] = attempted

        # Show AI explanation only after submit
        session['show_explanation'] = True
        key = f"{subject}_{idx}_{year}"
        if key not in session.get('explanations', {}):
            explanation = generate_explanation(idx, year, subject, q, selected, correct)
            session['explanations'][key] = explanation

        session.modified = True
        return redirect(url_for('quiz'))

    elif act == 'next' and idx < len(df) - 1:
        session['index'] = idx + 1
        session['show_explanation'] = False

    elif act == 'prev' and idx > 0:
        session['index'] = idx - 1
        session['show_explanation'] = False

    elif act == 'skip':
        attempted = session.get('attempted', {})
        attempted[str(idx)] = 'SKIPPED'
        session['attempted'] = attempted
        if idx < len(df) - 1:
            session['index'] = idx + 1
        session['show_explanation'] = False

    elif act == 'toggle_explanation':
        session['show_explanation'] = not session.get('show_explanation', False)

    elif act == 'reset':
        init_session_state(subject, year)

    return redirect(url_for('quiz'))


@app.route('/results')
def results():
    subject = session.get('subject', 'english')
    year = session.get('year', 2024)
    df = load_data(subject, year)
    attempted = session.get('attempted', {})
    results = []

    for i in range(len(df)):
        key = str(i)
        if key in attempted:
            user_answer = attempted[key]
            correct_answer = str(df.iloc[i]['Answer']).strip().upper()
            results.append({
                'Question_Number': i + 1,
                'Your_Answer': user_answer,
                'Correct_Answer': correct_answer,
                'Result': '✅ Correct' if user_answer == correct_answer else '❌ Incorrect'
            })

    return render_template('results.html', results=results, score=session.get('score', 0), total=len(df))


@app.route('/audio/<path:filename>')
def audio(filename):
    return send_from_directory(STATIC_AUDIO, filename)


@app.route("/proxy_image")
def proxy_image():
    """Safely load external images from WAEC dataset."""
    img_url = request.args.get("url")
    if not img_url:
        return Response("Missing image URL", status=400)
    try:
        r = requests.get(img_url, stream=True, timeout=5)
        if r.status_code == 200:
            return Response(r.content, mimetype="image/png")
        return Response("Image not found", status=404)
    except Exception:
        return Response("Error loading image", status=500)


if __name__ == "__main__":
    app.run(debug=True)
