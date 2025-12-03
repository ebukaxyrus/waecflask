import os
import re
from pathlib import Path
from flask import (
    Flask, render_template, request, redirect, url_for, session,
    send_from_directory, flash, Response
)
import pandas as pd
from dotenv import load_dotenv
import requests

# =============== OPENAI CLIENT ==================
try:
    from openai import OpenAI as OpenAIClient
    OPENAI_CLIENT_AVAILABLE = True
except:
    OPENAI_CLIENT_AVAILABLE = False

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-secret")

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "waec_data"
STATIC_AUDIO = BASE_DIR / "static" / "audio"
STATIC_AUDIO.mkdir(parents=True, exist_ok=True)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = None

if OPENAI_API_KEY and OPENAI_CLIENT_AVAILABLE:
    try:
        client = OpenAIClient(api_key=OPENAI_API_KEY)
    except:
        client = None


# ================ TEXT FORMAT HELPERS ==================
def format_question_text(text):
    if pd.isna(text) or not text:
        return ""
    text = str(text).strip()
    text = re.sub(r'_([^_]+)_', r'<u>\1</u>', text)
    text = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'\*([^*]+)\*', r'<em>\1</em>', text)
    return text


def clean_option_text(text):
    if pd.isna(text) or not text:
        return "Option missing"
    text = str(text).strip()
    text = re.sub(r'^[A-D]\.\s*', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text


# ================= LOAD QUESTION CSV ===================
def load_data(subject: str, year: int):
    filename = DATA_DIR / f"waec_{subject}_{year}_complete.csv"

    if not filename.exists():
        raise FileNotFoundError(f"CSV not found: {filename}")

    df = pd.read_csv(filename)

    if df.empty:
        raise ValueError("CSV file is empty.")

    required = ["Question", "OptionA", "OptionB", "OptionC", "OptionD", "Answer"]
    for r in required:
        if r not in df.columns:
            raise ValueError(f"Missing column: {r}")

    if "Image_URLs" not in df.columns:
        df["Image_URLs"] = ""

    df["Image_URLs_List"] = df["Image_URLs"].apply(
        lambda x: [u.strip() for u in str(x).split(",")] if str(x).strip() else []
    )

    df_filtered = df.dropna(subset=["Question", "Answer"])
    df_filtered = df_filtered[df_filtered["Answer"].str.upper().isin(["A", "B", "C", "D"])]

    for opt in ["OptionA", "OptionB", "OptionC", "OptionD"]:
        df_filtered[opt] = df_filtered[opt].fillna(f"{opt[-1]} missing")

    return df_filtered.reset_index(drop=True)


# ================= EXPLANATION + TTS ===================
def generate_explanation(idx, year, subject, q, selected, correct):

    if not client:
        return "AI explanation unavailable — missing API key."

    try:
        prompt = (
            f"Explain briefly (2–3 sentences) why option {correct} is correct "
            f"for this WAEC {subject.title()} question:\n\n{q['Question']}\n\n"
            f"A. {q['OptionA']}\nB. {q['OptionB']}\nC. {q['OptionC']}\nD. {q['OptionD']}\n\n"
        )

        if selected != correct:
            prompt += f"The student chose {selected}. Explain why that is incorrect."

        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a helpful WAEC tutor."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.5,
            max_tokens=150
        )

        explanation = completion.choices[0].message.content.strip()

        # ---- TTS ----
        valid_voices = [
            "alloy", "echo", "fable", "onyx", "nova", "shimmer",
            "coral", "verse", "ballad", "ash", "sage", "marin", "cedar"
        ]

        voice = session.get("voice", "verse")
        if voice not in valid_voices:
            voice = "verse"


        audio_path = STATIC_AUDIO / f"explanation_{subject}_{idx}_{year}.mp3"

        tts_audio = client.audio.speech.create(
            model="gpt-4o-mini-tts",
            voice=voice,
            input=explanation
        )

        with open(audio_path, "wb") as f:
            f.write(tts_audio.read())

        return explanation

    except Exception as e:
        return f"⚠️ Error generating explanation: {e}"


# ================= INIT SESSION ===================
def init_session_state(subject, year):
    session["subject"] = subject
    session["year"] = year
    session["index"] = 0
    session["score"] = 0
    session["attempted"] = {}
    session["show_explanation"] = False
    session["explanations"] = {}
    session["voice"] = session.get("voice", "verse")  # default female voice


# ================= ROUTES ============================
@app.route("/")
def index():
    years = list(range(2024, 2014, -1))
    return render_template("index.html", years=years)


@app.route("/start", methods=["POST"])
def start():
    subject = request.form.get("subject", "english")
    year = int(request.form.get("year", 2024))

    session.clear()
    load_data(subject, year)
    init_session_state(subject, year)

    flash(f"🎓 Starting {subject.capitalize()} {year} quiz", "info")
    return redirect(url_for("quiz"))


@app.route("/quiz")
def quiz():
    subject = session["subject"]
    year = session["year"]

    df = load_data(subject, year)
    idx = session["index"]

    q = df.iloc[idx].copy()
    q["Question"] = format_question_text(q["Question"])

    display_opts = {
        opt: f"{opt}. {clean_option_text(q[f'Option{opt}'])}"
        for opt in "ABCD"
    }

    attempted = session["attempted"]
    stored_answer = attempted.get(str(idx))

    answered = [v for v in attempted.values() if v != "SKIPPED"]
    accuracy = (session["score"] / len(answered)) * 100 if answered else 0
    progress = ((idx + 1) / len(df)) * 100

    return render_template(
        "question.html",
        q=q,
        idx=idx,
        subject=subject,
        year=year,
        display_opts=display_opts,
        stored_answer=stored_answer,
        score=session["score"],
        accuracy=accuracy,
        progress=progress,
        skipped_count=len([v for v in attempted.values() if v == "SKIPPED"]),
        total=len(df)
    )


@app.route("/action", methods=["POST"])
def action():
    act = request.form.get("action")
    subject = session["subject"]
    year = session["year"]

    df = load_data(subject, year)
    idx = session["index"]
    q = df.iloc[idx]

    if act == "submit":
        selected = request.form.get("selected")
        if not selected:
            flash("Select an option before submitting.", "warning")
            return redirect(url_for("quiz"))

        correct = q["Answer"].upper()
        attempted = session["attempted"]
        already = str(idx) in attempted

        attempted[str(idx)] = selected
        session["attempted"] = attempted

        if not already:
            if selected == correct:
                session["score"] += 1
                flash(f"✅ Correct! ({correct})", "success")
            else:
                flash(f"❌ Incorrect. Correct answer: {correct}", "danger")

        session["show_explanation"] = True
        key = f"{subject}_{idx}_{year}"

        if key not in session["explanations"]:
            session["explanations"][key] = generate_explanation(
                idx, year, subject, q, selected, correct
            )

        session.modified = True
        return redirect(url_for("quiz"))

    # Navigation
    if act == "next":
        if idx < len(df) - 1:
            session["index"] += 1
        session["show_explanation"] = False

    elif act == "prev":
        if idx > 0:
            session["index"] -= 1
        session["show_explanation"] = False

    elif act == "skip":
        session["attempted"][str(idx)] = "SKIPPED"
        if idx < len(df) - 1:
            session["index"] += 1
        session["show_explanation"] = False

    elif act == "toggle_explanation":
        session["show_explanation"] = not session["show_explanation"]

    elif act == "reset":
        init_session_state(subject, year)

    elif act == "change_voice":
    # 1. Update selected voice
        new_voice = request.form.get("voice", "verse")
        session["voice"] = new_voice

        # 2. Regenerate audio for current question
        key = f"{subject}_{idx}_{year}"

        # If explanation already exists, reuse it but regenerate the AUDIO
        if key in session["explanations"]:
            explanation_text = session["explanations"][key]

            audio_path = STATIC_AUDIO / f"explanation_{subject}_{idx}_{year}.mp3"

            try:
                # Regenerate audio with new voice
                tts_audio = client.audio.speech.create(
                    model="gpt-4o-mini-tts",
                    voice=new_voice,
                    input=explanation_text
                )
                
                # Save new audio
                with open(audio_path, "wb") as f:
                    f.write(tts_audio.read())

                flash(f"🔊 Voice changed to {new_voice.capitalize()} (Audio updated)", "success")

            except Exception as e:
                flash(f"⚠️ Error updating audio: {e}", "danger")

        else:
            flash("ℹ️ Voice updated. Explanation audio will apply on your next submit.", "info")

        session.modified = True
        return redirect(url_for("quiz"))
    

    


@app.route("/results")
def results():
    subject = session["subject"]
    year = session["year"]
    df = load_data(subject, year)

    attempted = session["attempted"]
    results = []

    for i in range(len(df)):
        if str(i) in attempted:
            ans = attempted[str(i)]
            correct = df.iloc[i]["Answer"].upper()
            results.append({
                "Question_Number": i + 1,
                "Your_Answer": ans,
                "Correct_Answer": correct,
                "Result": "✅ Correct" if ans == correct else "❌ Incorrect"
            })

    return render_template("results.html", results=results, score=session["score"], total=len(df))


@app.route("/audio/<path:filename>")
def audio(filename):
    return send_from_directory(STATIC_AUDIO, filename)


@app.route("/proxy_image")
def proxy_image():
    url = request.args.get("url")
    if not url:
        return Response("Missing URL", status=400)

    try:
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            return Response(r.content, mimetype="image/png")
        return Response("Not found", 404)
    except:
        return Response("Image load error", 500)


if __name__ == "__main__":
    app.run(debug=True)
