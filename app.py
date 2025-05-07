import os
import asyncio
import html
from datetime import datetime
import pdfkit
import webbrowser
from dotenv import load_dotenv
from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for, session
from werkzeug.utils import secure_filename
import tempfile
import google.generativeai as genai

# 初始化 Flask
app = Flask(__name__)
app.secret_key = 'your_secret_key'
app.config['UPLOAD_FOLDER'] = 'uploads'

# 確保上傳資料夾存在
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# 載入 .env
load_dotenv()

# wkhtmltopdf 路徑
WKHTMLTOPDF_PATH = r"C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe"
pdfkit_config = pdfkit.configuration(wkhtmltopdf=WKHTMLTOPDF_PATH)

# HTML 模板
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="UTF-8">
<title>英文寫作分析報告</title>
<style>
    body {{
        font-family: "Times New Roman", serif;
        margin: 50px;
        line-height: 1.8;
        font-size: 16px;
    }}
    h1 {{
        text-align: center;
        font-size: 28px;
        margin-bottom: 40px;
    }}
    h2 {{
        font-size: 22px;
        color: #2c3e50;
        margin-top: 30px;
        margin-bottom: 10px;
    }}
    .timestamp {{
        text-align: right;
        font-size: 12px;
        color: gray;
        margin-bottom: 30px;
    }}
    .highlight {{
        color: red;
        font-weight: bold;
    }}
    p {{
        text-indent: 2em;
        margin-top: 10px;
    }}
</style>
</head>
<body>
<h1>英文寫作分析報告</h1>
<div class="timestamp">生成時間：{timestamp}</div>
{content}
</body>
</html>
"""

SECTION_TEMPLATE = """
<h2>{title}</h2>
{content}
"""

# 分析文章
async def analyze_text(text_content, model_client):
    prompt = (
        "請根據下列格式分析這篇英文文章，並用正式繁體中文回答，不要有AI回應開場白。\n\n"
        "請按照以下五個部分依序分析，並清楚標示標題（每個標題前請加上『第X部分：』）：\n\n"
        "第1部分：文章內容統整：說明這篇文章的重點。\n"
        "第2部分：內容分析：【敘事方式說明】與【佳句統整】。\n"
        "第3部分：文章優、缺點：個別條列【優點】、【缺點】，並簡要說明【整體回饋】。\n"
        "第4部分：文法與用詞錯誤：用數字條列指出【原文】和【改進方式】。\n"
        "第5部分：文法、單字替換：用數字條列【原文】、【建議替換內容】、【簡要說明建議原因】\n\n"
        "注意：文中請用紅色字標出第4部分的英文文法或用詞錯誤之處（用<span class='highlight'>標記內容</span>），並不要使用粗體字。\n"
        "請盡量詳細分析。\n"
        "回覆時直接開始，不要有開場白。\n\n"
        f"以下為文章內容：\n\n{text_content}"
    )
    try:
        response = await model_client.generate_content_async(prompt)
        return response.text
    except Exception as e:
        print("呼叫API時出錯:", e)
        return "目前無法取得回應，請稍後再試。"

# 生成範例文章
async def generate_sample_article(text_content, model_client):
    prompt = (
        "請根據以下英文文章的主題，重新寫一篇相同主題但敘事方式不同或更優秀的英文範例文章。"
        "新文章請自然流暢、用字適切且文法正確。請直接給出完整英文文章，不要有任何中文說明或開場白。\n\n"
        f"以下為原始文章：\n\n{text_content}"
    )
    try:
        response = await model_client.generate_content_async(prompt)
        return response.text
    except Exception as e:
        print("產生範例文章時出錯:", e)
        return "目前無法取得範例文章，請稍後再試。"

# 產生報告 HTML
def generate_html_report(analysis_text, sample_article_text):
    sections = []
    current_title = None
    current_content = []

    for line in analysis_text.split("\n"):
        line = line.strip()
        if not line:
            continue
        if any(kw in line for kw in ["第1部分", "第2部分", "第3部分", "第4部分", "第5部分"]):
            if current_title:
                sections.append((current_title, "\n".join(current_content)))
            current_title = line
            current_content = []
        else:
            current_content.append(line)
    if current_title:
        sections.append((current_title, "\n".join(current_content)))

    formatted_sections = []
    for title, content in sections:
        formatted_sections.append(SECTION_TEMPLATE.format(
            title=title,
            content="<p>" + content.replace("\n", "</p><p>") + "</p>"
        ))

    sample_article_html = html.escape(sample_article_text).replace('\n', '</p><p>')
    formatted_sections.append(SECTION_TEMPLATE.format(
        title="範例文章參考",
        content=f"<p>{sample_article_html}</p>"
    ))

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return HTML_TEMPLATE.format(timestamp=timestamp, content="\n".join(formatted_sections))

# 分析流程
async def process_text(text_content):
    gemini_api_key = os.environ.get("GEMINI_API_KEY")
    if not gemini_api_key:
        raise ValueError("請設定環境變數 GEMINI_API_KEY")

    genai.configure(api_key=gemini_api_key)
    model = genai.GenerativeModel(model_name="gemini-1.5-flash-latest")

    analysis_text = await analyze_text(text_content, model)
    sample_article_text = await generate_sample_article(text_content, model)

    if not analysis_text or not sample_article_text:
        return "分析失敗，請稍後再試。"

    return generate_html_report(analysis_text, sample_article_text)

# 登入頁面
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if username == 'admin' and password == 'password123':
            session['username'] = username
            return redirect(url_for('index'))
        else:
            return render_template("login.html", error="帳號或密碼錯誤")
    return render_template("login.html")

# 登出
@app.route('/logout')
def logout():
    session.pop('username', None)
    return redirect(url_for('login'))

# 主頁與分析處理
@app.route("/", methods=["GET", "POST"])
def index():
    if 'username' not in session:
        return redirect(url_for('login'))

    if request.method == "POST":
        input_text = request.form.get("text_content", "")
        uploaded_file = request.files.get("file")

        if uploaded_file and uploaded_file.filename.endswith(".txt"):
            filename = secure_filename(uploaded_file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            uploaded_file.save(filepath)
            with open(filepath, "r", encoding="utf-8") as f:
                input_text = f.read()

        if not input_text.strip():
            return jsonify({"result": "請輸入文章內容或上傳檔案。"})

        analysis_html = asyncio.run(process_text(input_text))

        # 產生 PDF
        output_path = os.path.join("static", "downloads", "analysis_result.pdf")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        pdfkit.from_string(analysis_html, output_path, configuration=pdfkit_config)

        return jsonify({
            "result": analysis_html,
            "pdf_url": "/static/downloads/analysis_result.pdf"
        })

    return render_template("index.html", username=session['username'])

if __name__ == '__main__':
    app.run(debug=True)
