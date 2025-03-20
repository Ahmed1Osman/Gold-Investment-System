import streamlit as st
import yfinance as yf
import requests
from langchain_huggingface import HuggingFaceEndpoint
from datetime import datetime
import pandas as pd
import io
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
import time
import re

# Set page configuration
st.set_page_config(page_title="Gold Investment System", page_icon="💰", layout="wide")

# API Keys (store in secrets.toml)
ALPHA_VANTAGE_API_KEY = st.secrets["ALPHA_VANTAGE_API_KEY"]
NEWS_API_KEY = st.secrets["NEWS_API_KEY"]
HUGGINGFACE_API_KEY = st.secrets["HUGGINGFACE_API_KEY"]
EXCHANGE_RATE_API_KEY = st.secrets["EXCHANGE_RATE_API_KEY"]

# Fetch USD to EGP exchange rate
def get_usd_to_egp_rate():
    url = f"https://v6.exchangerate-api.com/v6/{EXCHANGE_RATE_API_KEY}/latest/USD"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        return data["conversion_rates"]["EGP"] if "conversion_rates" in data else 47.5
    except (requests.RequestException, ValueError):
        st.warning("تعذر جلب سعر الصرف. يتم استخدام 47.5 جنيه/دولار")
        return 47.5

# Global cache for gold price
cached_price = None
cache_timestamp = 0
CACHE_DURATION = 300  # 5 minutes in seconds

# Fetch current gold price from API, tailored for Egypt
def get_current_price(_=None):
    global cached_price, cache_timestamp
    current_time = time.time()
    
    if cached_price and (current_time - cache_timestamp) < CACHE_DURATION:
        return cached_price
    
    # Try Yahoo Finance first
    try:
        gold = yf.Ticker("GC=F")  # Gold futures symbol
        hist = gold.history(period="1d")
        if not hist.empty:
            usd_price_per_oz = hist["Close"].iloc[-1]
        else:
            raise ValueError("لا توجد بيانات من Yahoo Finance")
    except Exception as e:
        st.warning(f"فشل Yahoo Finance: {str(e)}. الرجوع إلى Alpha Vantage.")
        # Fallback to Alpha Vantage
        url = f"https://www.alphavantage.co/query?function=CURRENCY_EXCHANGE_RATE&from_currency=XAU&to_currency=USD&apikey={ALPHA_VANTAGE_API_KEY}"
        try:
            response = requests.get(url)
            response.raise_for_status()
            data = response.json()
            if "Realtime Currency Exchange Rate" in data:
                usd_price_per_oz = float(data["Realtime Currency Exchange Rate"]["5. Exchange Rate"])
            else:
                raise KeyError("البيانات المتوقعة غير موجودة في رد Alpha Vantage")
        except (requests.RequestException, KeyError, ValueError) as e:
            st.error(f"فشل Alpha Vantage: {str(e)}. استخدام قيمة افتراضية.")
            usd_price_per_oz = 2000.0  # Default value
    
    # Convert to EGP per gram (21K)
    egp_rate = get_usd_to_egp_rate()
    egp_price_per_gram_21k = (usd_price_per_oz * egp_rate / 31.1035) * 0.875
    cached_price = {
        "usd_per_oz": usd_price_per_oz,
        "egp_per_gram_21k": egp_price_per_gram_21k,
        "text": f"سعر الذهب الحالي: {egp_price_per_gram_21k:.2f} جنيه/جرام (21 قيراط)" if st.session_state.get('language', 'العربية') == "العربية" else f"Current gold price: {egp_price_per_gram_21k:.2f} EGP/gram (21K)"
    }
    cache_timestamp = current_time
    return cached_price

# Historical data
def get_historical_data(_=None):
    try:
        gold = yf.Ticker("GC=F")
        hist = gold.history(period="1y")
        egp_rate = get_usd_to_egp_rate()
        avg_usd_price = hist["Close"].mean()
        avg_egp_price_per_gram_21k = (avg_usd_price * egp_rate / 31.1035) * 0.875
        return f"متوسط سعر الذهب خلال سنة: {avg_egp_price_per_gram_21k:.2f} جنيه/جرام (21 قيراط)" if st.session_state.get('language', 'العربية') == "العربية" else f"Average gold price over 1 year: {avg_egp_price_per_gram_21k:.2f} EGP/gram (21K)"
    except Exception:
        return "تعذر جلب بيانات الأسعار التاريخية" if st.session_state.get('language', 'العربية') == "العربية" else "Failed to fetch historical price data"

# Fetch news (updated to return list of articles)
def get_news(_=None):
    url = f"https://newsapi.org/v2/everything?q=gold+egypt&apiKey={NEWS_API_KEY}"
    try:
        response = requests.get(url)
        response.raise_for_status()
        articles = response.json()["articles"]
        return articles[:3]
    except (requests.RequestException, KeyError):
        return []

# Price change with volatility
def get_price_change(_=None):
    try:
        gold = yf.Ticker("GC=F")
        hist = gold.history(period="5d")
        if len(hist) >= 2:
            today_usd = hist["Close"].iloc[-1]
            yesterday_usd = hist["Close"].iloc[-2]
            egp_rate = get_usd_to_egp_rate()
            change_egp_per_gram = ((today_usd - yesterday_usd) * egp_rate / 31.1035) * 0.875
            percent_change = (change_egp_per_gram / (yesterday_usd * egp_rate / 31.1035 * 0.875)) * 100
            trend = "قد يرتفع" if change_egp_per_gram > 0 else "قد ينخفض"
            return f"تغير سعر الذهب اليوم: {change_egp_per_gram:.2f} جنيه/جرام ({percent_change:.2f}%) - {trend}" if st.session_state.get('language', 'العربية') == "العربية" else f"Gold price change today: {change_egp_per_gram:.2f} EGP/gram ({percent_change:.2f}%) - {'May rise' if change_egp_per_gram > 0 else 'May fall'}"
        return "لا توجد بيانات كافية" if st.session_state.get('language', 'العربية') == "العربية" else "Insufficient data"
    except Exception:
        return "تعذر حساب تغير السعر" if st.session_state.get('language', 'العربية') == "العربية" else "Failed to calculate price change"

# Calculate gold purchase (uses effective price)
def calculate_gold_purchase(amount_str):
    try:
        amount = float(amount_str.replace("ج", "").replace(",", ""))
        if amount <= 0:
            return "يرجى إدخال مبلغ أكبر من 0" if st.session_state.get('language', 'العربية') == "العربية" else "Please enter an amount greater than 0"
        if "effective_price" in st.session_state and st.session_state.effective_price:
            current_price_egp = st.session_state.effective_price
            grams = amount / current_price_egp
            return f"بـ {amount:.2f} جنيه، يمكنك شراء {grams:.2f} جرام (21 قيراط) بسعر {current_price_egp:.2f} جنيه/جرام" if st.session_state.get('language', 'العربية') == "العربية" else f"With {amount:.2f} EGP, you can buy {grams:.2f} grams (21K) at {current_price_egp:.2f} EGP/gram"
        return "تعذر جلب السعر الحالي" if st.session_state.get('language', 'العربية') == "العربية" else "Failed to fetch current price"
    except ValueError:
        return "يرجى إدخال المبلغ بشكل صحيح" if st.session_state.get('language', 'العربية') == "العربية" else "Please enter the amount correctly"

# Gold savings plan (uses effective price)
def calculate_savings_plan(amount_str, months=12):
    try:
        monthly_amount = float(amount_str.replace("ج", "").replace(",", ""))
        if monthly_amount <= 0 or months <= 0:
            return "يرجى إدخال مبلغ شهري وعدد أشهر أكبر من 0" if st.session_state.get('language', 'العربية') == "العربية" else "Please enter a monthly amount and number of months greater than 0"
        if "effective_price" in st.session_state and st.session_state.effective_price:
            current_price_egp = st.session_state.effective_price
            total_amount = monthly_amount * months
            total_grams = total_amount / current_price_egp
            return f"بادخار {monthly_amount:.2f} جنيه شهريًا لمدة {months} شهرًا، يمكنك شراء {total_grams:.2f} جرام (21 قيراط)" if st.session_state.get('language', 'العربية') == "العربية" else f"By saving {monthly_amount:.2f} EGP monthly for {months} months, you can buy {total_grams:.2f} grams (21K)"
        return "تعذر جلب السعر الحالي" if st.session_state.get('language', 'العربية') == "العربية" else "Failed to fetch current price"
    except ValueError:
        return "يرجى إدخال المبلغ الشهري بشكل صحيح" if st.session_state.get('language', 'العربية') == "العربية" else "Please enter the monthly amount correctly"

# Streamlit App
st.title("💰  Gold Investment System")
language = st.sidebar.selectbox("اللغة", ["العربية", "English"])
st.session_state.language = language
st.markdown("**تابع الذهب، استثمر، وادخر بسهولة بالجنيه المصري - مصمم خصيصًا للسوق المصري**" if language == "العربية" else "**Track gold, invest, and save easily in EGP - Designed specifically for the Egyptian market**")

# Sidebar for manual price input
with st.sidebar:
    st.header("إعدادات" if language == "العربية" else "Settings")
    st.write("**ملاحظة:** يمكنك إدخال سعر محلي يدوي ليعكس أسعار السوق المصري" if language == "العربية" else "**Note:** You can enter a local manual price to reflect Egyptian market rates")
    use_manual_price = st.checkbox("استخدام سعر يدوي للذهب" if language == "العربية" else "Use manual gold price", key="use_manual_price")
    if use_manual_price:
        manual_price = st.number_input("سعر الذهب (جنيه/جرام)" if language == "العربية" else "Gold price (EGP/gram)", min_value=0.0, value=0.0, key="manual_price")
    else:
        manual_price = None

# Set effective price
if use_manual_price and manual_price > 0:
    effective_price = manual_price
    effective_price_text = f"سعر الذهب الحالي (يدوي): {effective_price:.2f} جنيه/جرام" if language == "العربية" else f"Current gold price (manual): {effective_price:.2f} EGP/gram"
else:
    api_price_data = get_current_price()
    if "egp_per_gram_21k" in api_price_data:
        effective_price = api_price_data["egp_per_gram_21k"]
        effective_price_text = api_price_data["text"]
    else:
        effective_price = None
        effective_price_text = "تعذر جلب سعر الذهب" if language == "العربية" else "Failed to fetch gold price"
st.session_state.effective_price = effective_price
st.session_state.effective_price_text = effective_price_text

# Initialize HuggingFace model
try:
    llm = HuggingFaceEndpoint(
        repo_id="google/flan-t5-large",
        huggingfacehub_api_token=HUGGINGFACE_API_KEY
    )
except Exception as e:
    st.warning(f"فشل تهيئة نموذج اللغة: {str(e)}. سيتم استخدام الردود الأساسية." if language == "العربية" else f"Failed to initialize language model: {str(e)}. Using basic responses.")
    llm = None

# Custom query processing function
def process_query(query):
    query_lower = query.lower()
    
    # Check for keywords related to tools
    if "سعر" in query_lower or "price" in query_lower:
        return st.session_state.effective_price_text
    elif "أخبار" in query_lower or "news" in query_lower:
        news_articles = get_news()
        if news_articles:
            return "\n".join([f"{article['title']} - {article['description']}" for article in news_articles])
        else:
            return "تعذر جلب الأخبار" if language == "العربية" else "Failed to fetch news"
    elif "تغير" in query_lower or "change" in query_lower:
        return get_price_change()
    elif "كم ذهب" in query_lower or "how much gold" in query_lower:
        try:
            amount_str = re.search(r'\d+', query).group()
            return calculate_gold_purchase(amount_str)
        except:
            return "يرجى إدخال المبلغ بشكل صحيح" if language == "العربية" else "Please enter the amount correctly"
    else:
        # Use the HuggingFace model for general responses
        if llm:
            try:
                response = llm(query)
                return response
            except Exception as e:
                return f"Error generating response: {str(e)}"
        else:
            return "يرجى السؤال عن السعر، التغير، الكمية، أو الأخبار" if language == "العربية" else "Please ask about price, change, amount, or news"

# Tabs
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(
    ["محفظتك", "حاسبة الاستثمار", "اتجاهات الأسعار", "اسأل عن الذهب", "أخبار الذهب", "تعليم"] if language == "العربية" else 
    ["Your Portfolio", "Investment Calculator", "Price Trends", "Ask About Gold", "Gold News", "Education"]
)

# Portfolio Tab
with tab1:
    st.header("محفظتك" if language == "العربية" else "Your Portfolio")
    grams_owned = st.number_input("كمية الذهب (جرام)" if language == "العربية" else "Gold Amount (grams)", min_value=0.0, value=0.0)
    purchase_price_egp = st.number_input("سعر الشراء (جنيه/جرام)" if language == "العربية" else "Purchase Price (EGP/gram)", min_value=0.0, value=0.0)
    if grams_owned > 0 and purchase_price_egp > 0 and st.session_state.effective_price:
        current_value = grams_owned * st.session_state.effective_price
        profit_loss = grams_owned * (st.session_state.effective_price - purchase_price_egp)
        st.markdown(f"**القيمة الحالية:** {current_value:.2f} جنيه" if language == "العربية" else f"**Current Value:** {current_value:.2f} EGP")
        st.markdown(f"**الربح/الخسارة:** {profit_loss:.2f} جنيه" if language == "العربية" else f"**Profit/Loss:** {profit_loss:.2f} EGP")
        if st.button("تصدير تقرير" if language == "العربية" else "Export Report"):
            buffer = io.BytesIO()
            p = canvas.Canvas(buffer, pagesize=letter)
            p.drawString(100, 750, f"تقرير المحفظة - {datetime.now().strftime('%Y-%m-%d')}" if language == "العربية" else f"Portfolio Report - {datetime.now().strftime('%Y-%m-%d')}")
            p.drawString(100, 730, f"كمية الذهب: {grams_owned:.2f} جرام" if language == "العربية" else f"Gold Amount: {grams_owned:.2f} grams")
            p.drawString(100, 710, f"القيمة الحالية: {current_value:.2f} جنيه" if language == "العربية" else f"Current Value: {current_value:.2f} EGP")
            p.drawString(100, 690, f"الربح/الخسارة: {profit_loss:.2f} جنيه" if language == "العربية" else f"Profit/Loss: {profit_loss:.2f} EGP")
            p.showPage()
            p.save()
            buffer.seek(0)
            st.download_button("تنزيل PDF" if language == "العربية" else "Download PDF", buffer, "portfolio_report.pdf", "application/pdf")

# Investment Calculator Tab
with tab2:
    st.header("حاسبة الاستثمار" if language == "العربية" else "Investment Calculator")
    col1, col2 = st.columns(2)
    with col1:
        investment_amount = st.number_input("المبلغ (جنيه)" if language == "العربية" else "Amount (EGP)", min_value=0.0, value=0.0)
        if st.button("احسب الكمية" if language == "العربية" else "Calculate Amount"):
            if st.session_state.effective_price:
                grams = investment_amount / st.session_state.effective_price
                st.write(f"بـ {investment_amount:.2f} جنيه، يمكنك شراء {grams:.2f} جرام (21 قيراط)" if language == "العربية" else f"With {investment_amount:.2f} EGP, you can buy {grams:.2f} grams (21K)")
            else:
                st.write("تعذر جلب السعر الحالي" if language == "العربية" else "Failed to fetch current price")
    with col2:
        monthly_saving = st.number_input("الادخار الشهري (جنيه)" if language == "العربية" else "Monthly Saving (EGP)", min_value=0.0, value=0.0)
        months = st.slider("عدد الأشهر" if language == "العربية" else "Months", 1, 36, 12)
        savings_goal = st.number_input("هدف الادخار (جرام)" if language == "العربية" else "Savings Goal (grams)", min_value=0.0, value=10.0)
        if st.button("احسب خطة الادخار" if language == "العربية" else "Calculate Savings Plan"):
            if st.session_state.effective_price:
                total_amount = monthly_saving * months
                total_grams = total_amount / st.session_state.effective_price
                st.write(f"بادخار {monthly_saving:.2f} جنيه شهريًا لمدة {months} شهرًا، يمكنك شراء {total_grams:.2f} جرام (21 قيراط)" if language == "العربية" else f"By saving {monthly_saving:.2f} EGP monthly for {months} months, you can buy {total_grams:.2f} grams (21K)")
                progress = min(total_grams / savings_goal, 1.0)
                st.progress(progress)
                st.write(f"تقدم نحو الهدف: {total_grams:.2f}/{savings_goal:.2f} جرام" if language == "العربية" else f"Progress toward goal: {total_grams:.2f}/{savings_goal:.2f} grams")
            else:
                st.write("تعذر جلب السعر الحالي" if language == "العربية" else "Failed to fetch current price")

# Price Trends Tab
with tab3:
    st.header("اتجاهات الأسعار" if language == "العربية" else "Price Trends")
    period = st.selectbox("اختر الفترة" if language == "العربية" else "Select Period", ["1 شهر", "3 أشهر", "6 أشهر", "سنة", "سنتان", "5 سنوات"] if language == "العربية" else ["1 month", "3 months", "6 months", "1 year", "2 years", "5 years"], index=3)
    period_map = {"1 شهر": "1mo", "3 أشهر": "3mo", "6 أشهر": "6mo", "سنة": "1y", "سنتان": "2y", "5 سنوات": "5y", "1 month": "1mo", "3 months": "3mo", "6 months": "6mo", "1 year": "1y", "2 years": "2y", "5 years": "5y"}
    if st.button("اعرض الاتجاهات" if language == "العربية" else "Show Trends"):
        try:
            hist = yf.Ticker("GC=F").history(period=period_map[period])
            egp_rate = get_usd_to_egp_rate()
            hist["Close_EGP"] = (hist["Close"] * egp_rate / 31.1035) * 0.875
            for window in [50, 200]:
                hist[f"MA{window}"] = hist["Close_EGP"].rolling(window=window).mean()
            st.line_chart(hist[["Close_EGP", "MA50", "MA200"]])
            avg_return = ((hist["Close_EGP"].iloc[-1] - hist["Close_EGP"].iloc[0]) / hist["Close_EGP"].iloc[0]) * 100
            st.write(f"متوسط العائد خلال {period}: {avg_return:.2f}%" if language == "العربية" else f"Average Return over {period}: {avg_return:.2f}%")
            change_text = get_price_change()
            if "تغير سعر الذهب" in change_text or "Gold price change" in change_text:
                percent_change = float(change_text.split("(")[1].split("%")[0])
                volatility = min(abs(percent_change) / 5, 1.0)
                st.progress(volatility)
                st.write(f"مستوى التقلب: {'عالي' if volatility > 0.7 else 'متوسط' if volatility > 0.3 else 'منخفض'}" if language == "العربية" else f"Volatility Level: {'High' if volatility > 0.7 else 'Medium' if volatility > 0.3 else 'Low'}")
        except Exception:
            st.write("تعذر عرض الاتجاهات" if language == "العربية" else "Failed to show trends")

# Ask About Gold Tab
with tab4:
    st.header("اسأل عن الذهب" if language == "العربية" else "Ask About Gold")
    st.subheader("أمثلة على الأسئلة" if language == "العربية" else "Example Questions")
    st.write("- كم سعر الذهب اليوم؟" if language == "العربية" else "- What’s the gold price today?")
    st.write("- كم ذهب أشتري بـ 5000 جنيه؟" if language == "العربية" else "- How much gold can I buy with 5000 EGP?")
    st.write("- ما هو تغير سعر الذهب اليوم؟" if language == "العربية" else "- What’s the price change today?")
    st.write("- ما هي أخبار الذهب في مصر؟" if language == "العربية" else "- What’s the latest gold news in Egypt?")
    
    query = st.text_input(
        "اكتب سؤالك" if language == "العربية" else "Type your question",
        placeholder="مثل: 'كم ذهب أشتري بـ 5000؟'" if language == "العربية" else "e.g., 'How much gold for 5000 EGP?'",
        key="query_input"
    )
    if query:
        with st.spinner("جاري معالجة سؤالك..." if language == "العربية" else "Processing your question..."):
            response = process_query(query)
            st.markdown(f"**{'الإجابة' if language == 'العربية' else 'Answer'}:** {response}")

# Gold News Tab
with tab5:
    st.header("أخبار الذهب" if language == "العربية" else "Gold News")
    articles = get_news()
    if articles:
        for article in articles:
            st.subheader(article['title'])
            st.write(article['description'])
            if 'url' in article:
                st.write(f"[{'اقرأ المزيد' if language == 'العربية' else 'Read more'}]({article['url']})")
    else:
        st.write("تعذر جلب الأخبار" if language == "العربية" else "Failed to fetch news")

# Education Tab
with tab6:
    st.header("تعليم" if language == "العربية" else "Education")
    st.write("**لماذا تستثمر في الذهب؟**" if language == "العربية" else "**Why Invest in Gold?**")
    st.write("الذهب يُعتبر ملاذًا آمنًا يحمي من التضخم والتقلبات الاقتصادية، خاصة في مصر حيث يواجه الجنيه تقلبات أمام الدولار." if language == "العربية" else "Gold is a safe haven that protects against inflation and economic volatility, especially in Egypt where the EGP faces fluctuations against the USD.")
    st.write("**كيف يحمي الذهب من التضخم؟**" if language == "العربية" else "**How Does Gold Protect Against Inflation?**")
    st.write("عندما يرتفع التضخم، يتراجع قيمة العملات الورقية، لكن الذهب غالبًا ما يرتفع في القيمة، مما يحافظ على قوة شرائك." if language == "العربية" else "When inflation rises, paper currencies lose value, but gold often increases in value, preserving your purchasing power.")

# Custom Alerts
with st.expander("تنبيهات الأسعار" if language == "العربية" else "Price Alerts"):
    alert_price = st.number_input("حدد سعر التنبيه (جنيه/جرام)" if language == "العربية" else "Set alert price (EGP/gram)", min_value=0.0, value=0.0)
    if alert_price > 0 and st.session_state.effective_price:
        current_price = st.session_state.effective_price
        if current_price <= alert_price:
            st.success(f"تنبيه: السعر الحالي {current_price:.2f} جنيه/جرام أقل من أو يساوي {alert_price:.2f}!" if language == "العربية" else f"Alert: Current price {current_price:.2f} EGP/gram is at or below {alert_price:.2f}!")
        else:
            st.info(f"السعر الحالي {current_price:.2f} جنيه/جرام أعلى من {alert_price:.2f}" if language == "العربية" else f"Current price {current_price:.2f} EGP/gram is above {alert_price:.2f}")

# Disclaimer
st.markdown("*تنبيه: هذا النظام للمعلومات فقط ومصمم للسوق المصري باستخدام البيانات المحلية. استشر مستشارًا ماليًا.*" if language == "العربية" else "*Note: This system is for information only and designed for the Egyptian market using local data. Consult a financial advisor.*", unsafe_allow_html=True)
