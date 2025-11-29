from flask import Flask, request, jsonify
import os
import asyncio
from playwright.async_api import async_playwright
from openai import OpenAI
import httpx
import json
import base64
from io import BytesIO
import re
import time
from datetime import datetime

app = Flask(__name__)

# Configuration - NEVER hardcode these, use environment variables
EMAIL = os.environ.get('STUDENT_EMAIL', '24f1002265@ds.study.iitm.ac.in')
SECRET = os.environ.get('STUDENT_SECRET')
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
GOOGLE_API_KEY = os.environ.get('GOOGLE_API_KEY')

# Initialize OpenAI client
openai_client = OpenAI(api_key=OPENAI_API_KEY)

class QuizSolver:
    def __init__(self, email, secret):
        self.email = email
        self.secret = secret
        self.start_time = None
        
    def time_remaining(self):
        """Check if within 3-minute window"""
        if not self.start_time:
            return 180
        elapsed = time.time() - self.start_time
        return max(0, 180 - elapsed)
    
    async def solve_quiz_chain(self, initial_url):
        """Solve a chain of quizzes"""
        self.start_time = time.time()
        current_url = initial_url
        results = []
        
        while current_url and self.time_remaining() > 10:
            try:
                print(f"[{self.time_remaining():.0f}s remaining] Solving: {current_url}")
                answer = await self.solve_single_quiz(current_url)
                
                print(f"Submitting answer: {answer}")
                response = await self.submit_answer(current_url, answer)
                
                results.append({
                    "url": current_url,
                    "answer": answer,
                    "correct": response.get('correct', False),
                    "reason": response.get('reason')
                })
                
                # Get next URL if available
                current_url = response.get('url')
                
                if response.get('correct') and not current_url:
                    print("✅ Quiz chain completed successfully!")
                    break
                elif not response.get('correct'):
                    print(f"❌ Wrong answer: {response.get('reason')}")
                    if current_url:
                        print(f"Moving to next quiz: {current_url}")
                    
            except Exception as e:
                print(f"❌ Error solving {current_url}: {str(e)}")
                results.append({
                    "url": current_url,
                    "error": str(e)
                })
                break
        
        return results
    
    async def solve_single_quiz(self, quiz_url):
        """Solve a single quiz task"""
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-setuid-sandbox']
            )
            page = await browser.new_page()
            
            try:
                await page.goto(quiz_url, wait_until='networkidle', timeout=30000)
                await page.wait_for_timeout(2000)
                
                # Extract all content
                text_content = await page.evaluate('() => document.body.innerText')
                
                # Find all links (potential data sources)
                links = await page.evaluate('''() => {
                    return Array.from(document.querySelectorAll('a'))
                        .map(a => ({href: a.href, text: a.innerText}))
                        .filter(link => link.href && link.text);
                }''')
                
                # Find submit URL from page
                submit_url = await page.evaluate('''() => {
                    const text = document.body.innerText;
                    const match = text.match(/Post.*answer.*to\\s+(https?:\\/\\/[^\\s]+)/i);
                    return match ? match[1] : null;
                }''')
                
                await browser.close()
                
                # Store submit URL for later
                self.current_submit_url = submit_url
                
                # Analyze with OpenAI
                answer = await self.analyze_and_solve(text_content, links, quiz_url)
                return answer
                
            except Exception as e:
                await browser.close()
                raise e
    
    async def analyze_and_solve(self, page_text, links, quiz_url):
        """Use OpenAI to analyze and solve"""
        
        links_text = "\n".join([f"- {link['text']}: {link['href']}" for link in links[:10]])
        
        prompt = f"""You are solving a data analysis quiz. Analyze this page and provide the answer.

PAGE CONTENT:
{page_text}

AVAILABLE LINKS:
{links_text}

QUIZ URL: {quiz_url}

Instructions:
1. Identify the question being asked
2. Determine what data source to use (check if any link points to a data file)
3. Describe what calculation or analysis is needed
4. If you can determine the answer from the page itself, provide it
5. If data needs to be downloaded, indicate which URL

Respond in JSON format:
{{
    "question": "the question being asked",
    "data_url": "URL to download data from (or null)",
    "submit_url": "URL where answer should be posted (or null)",
    "analysis_needed": "description of analysis",
    "answer": "the answer if determinable, otherwise null"
}}

IMPORTANT: Return ONLY the JSON, no other text."""

        try:
            response = openai_client.chat.completions.create(
                model="gpt-4o-mini",  # Fast and cost-effective
                messages=[
                    {"role": "system", "content": "You are a data analysis expert. Always respond with valid JSON only."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=2000
            )
            
            response_text = response.choices[0].message.content.strip()
            
            # Extract JSON
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
                
                # Store submit URL if found
                if result.get('submit_url'):
                    self.current_submit_url = result['submit_url']
                
                # If answer is already available, return it
                if result.get('answer') and result['answer'] not in ['null', None]:
                    return self.parse_answer(result['answer'])
                
                # Otherwise, fetch and process data
                if result.get('data_url'):
                    answer = await self.process_data_source(
                        result['data_url'],
                        result.get('analysis_needed', ''),
                        result.get('question', '')
                    )
                    return self.parse_answer(answer)
                    
        except Exception as e:
            print(f"OpenAI analysis error: {e}")
        
        # Fallback: try to extract answer directly
        return self.extract_answer_fallback(page_text)
    
    def parse_answer(self, answer):
        """Parse answer into appropriate type"""
        if answer is None:
            return None
        
        answer = str(answer).strip()
        
        # Remove quotes if present
        answer = answer.strip('"\'')
        
        # Try to convert to number
        try:
            if '.' in answer:
                return float(answer)
            return int(answer)
        except ValueError:
            pass
        
        # Try to convert to boolean
        if answer.lower() in ['true', 'yes']:
            return True
        if answer.lower() in ['false', 'no']:
            return False
        
        return answer
    
    def extract_answer_fallback(self, text):
        """Extract answer from text as fallback"""
        # Look for numbers
        numbers = re.findall(r'-?\d+\.?\d*', text)
        if numbers:
            try:
                num = numbers[-1]  # Often the answer is near the end
                return float(num) if '.' in num else int(num)
            except ValueError:
                pass
        
        return text.strip()[:100]  # Return first 100 chars as fallback
    
    async def process_data_source(self, data_url, analysis_task, question):
        """Download and process data from URL"""
        try:
            print(f"Downloading data from: {data_url}")
            async with httpx.AsyncClient(timeout=30.0) as http_client:
                response = await http_client.get(data_url)
                content = response.content
                
                # Process based on file type
                if data_url.endswith('.csv'):
                    return await self.process_csv(content, analysis_task, question)
                elif data_url.endswith(('.xlsx', '.xls')):
                    return await self.process_excel(content, analysis_task, question)
                elif data_url.endswith('.pdf'):
                    return await self.process_pdf(content, analysis_task, question)
                elif data_url.endswith(('.json', '.txt')):
                    return await self.process_text(content, analysis_task, question)
                else:
                    return await self.process_unknown_file(content, analysis_task, question)
                    
        except Exception as e:
            print(f"Error processing data source: {e}")
            return None
    
    async def process_csv(self, content, task, question):
        """Process CSV data"""
        try:
            import pandas as pd
            df = pd.read_csv(BytesIO(content))
            print(f"CSV loaded: {df.shape[0]} rows, {df.shape[1]} columns")
            print(f"Columns: {df.columns.tolist()}")
            return self.analyze_dataframe(df, task, question)
        except Exception as e:
            print(f"CSV processing error: {e}")
            return None
    
    async def process_excel(self, content, task, question):
        """Process Excel data"""
        try:
            import pandas as pd
            excel_file = pd.ExcelFile(BytesIO(content))
            
            print(f"Excel sheets: {excel_file.sheet_names}")
            
            # Check if task mentions specific sheet or page
            if 'page 2' in task.lower() or 'sheet 2' in task.lower():
                sheet_idx = 1 if len(excel_file.sheet_names) > 1 else 0
            else:
                sheet_idx = 0
            
            df = pd.read_excel(excel_file, sheet_name=sheet_idx)
            print(f"Excel loaded: {df.shape[0]} rows, {df.shape[1]} columns")
            return self.analyze_dataframe(df, task, question)
        except Exception as e:
            print(f"Excel processing error: {e}")
            return None
    
    async def process_pdf(self, content, task, question):
        """Process PDF data"""
        try:
            import PyPDF2
            pdf_reader = PyPDF2.PdfReader(BytesIO(content))
            
            text = ""
            if 'page 2' in task.lower():
                if len(pdf_reader.pages) > 1:
                    text = pdf_reader.pages[1].extract_text()
            else:
                for page in pdf_reader.pages:
                    text += page.extract_text() + "\n"
            
            print(f"PDF extracted: {len(text)} characters")
            return await self.analyze_text_with_ai(text, task, question)
        except Exception as e:
            print(f"PDF processing error: {e}")
            return None
    
    async def process_text(self, content, task, question):
        """Process text/JSON data"""
        try:
            text = content.decode('utf-8')
            return await self.analyze_text_with_ai(text, task, question)
        except Exception as e:
            print(f"Text processing error: {e}")
            return None
    
    async def process_unknown_file(self, content, task, question):
        """Process unknown file type"""
        try:
            text = content.decode('utf-8', errors='ignore')
            return await self.analyze_text_with_ai(text[:10000], task, question)
        except:
            return None
    
    def analyze_dataframe(self, df, task, question):
        """Analyze pandas DataFrame"""
        task_lower = (task + " " + question).lower()
        
        # Handle common operations
        if 'sum' in task_lower:
            col = self.find_target_column(df, task_lower)
            result = float(df[col].sum())
            print(f"Sum of '{col}': {result}")
            return result
            
        elif 'count' in task_lower or 'number of' in task_lower:
            result = len(df)
            print(f"Count: {result}")
            return result
            
        elif 'mean' in task_lower or 'average' in task_lower:
            col = self.find_target_column(df, task_lower)
            result = float(df[col].mean())
            print(f"Mean of '{col}': {result}")
            return result
            
        elif 'max' in task_lower or 'maximum' in task_lower:
            col = self.find_target_column(df, task_lower)
            result = float(df[col].max())
            print(f"Max of '{col}': {result}")
            return result
            
        elif 'min' in task_lower or 'minimum' in task_lower:
            col = self.find_target_column(df, task_lower)
            result = float(df[col].min())
            print(f"Min of '{col}': {result}")
            return result
        
        # Complex analysis - use OpenAI
        print("Using OpenAI for complex analysis...")
        return self.analyze_complex_data(df, task, question)
    
    def find_target_column(self, df, text):
        """Find the target column from text description"""
        # Look for column name in text
        for col in df.columns:
            if col.lower() in text:
                return col
        
        # Default to 'value' or last numeric column
        if 'value' in df.columns:
            return 'value'
        
        numeric_cols = df.select_dtypes(include=['number']).columns
        if len(numeric_cols) > 0:
            return numeric_cols[-1]
        
        return df.columns[-1]
    
    def analyze_complex_data(self, df, task, question):
        """Use OpenAI for complex data analysis"""
        summary = f"""Shape: {df.shape}
Columns: {df.columns.tolist()}
Data types: {df.dtypes.to_dict()}
First 5 rows:
{df.head().to_string()}
Last 2 rows:
{df.tail(2).to_string()}
Basic stats:
{df.describe().to_string()}"""
        
        try:
            response = openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a data analyst. Provide only the final answer value, nothing else."},
                    {"role": "user", "content": f"Data:\n{summary}\n\nQuestion: {question}\nTask: {task}\n\nProvide ONLY the numerical answer or value."}
                ],
                temperature=0,
                max_tokens=500
            )
            
            answer = response.choices[0].message.content.strip()
            print(f"OpenAI answer: {answer}")
            return self.parse_answer(answer)
            
        except Exception as e:
            print(f"OpenAI error: {e}")
            return None
    
    async def analyze_text_with_ai(self, text, task, question):
        """Use OpenAI to analyze text content"""
        try:
            response = openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a data analyst. Provide only the final answer value."},
                    {"role": "user", "content": f"Text:\n{text[:5000]}\n\nQuestion: {question}\nTask: {task}\n\nProvide ONLY the final answer."}
                ],
                temperature=0,
                max_tokens=500
            )
            
            answer = response.choices[0].message.content.strip()
            print(f"OpenAI answer: {answer}")
            return self.parse_answer(answer)
            
        except Exception as e:
            print(f"OpenAI error: {e}")
            return None
    
    async def submit_answer(self, quiz_url, answer):
        """Submit answer to quiz endpoint"""
        # Use stored submit URL or construct from quiz URL
        if hasattr(self, 'current_submit_url') and self.current_submit_url:
            submit_url = self.current_submit_url
        else:
            # Try to extract quiz ID and construct submit URL
            quiz_id_match = re.search(r'/quiz-?(\d+)', quiz_url)
            if quiz_id_match:
                base_url = quiz_url.rsplit('/', 1)[0]
                submit_url = f"{base_url}/submit"
            else:
                submit_url = quiz_url.replace('/quiz', '/submit')
        
        payload = {
            "email": self.email,
            "secret": self.secret,
            "url": quiz_url,
            "answer": answer
        }
        
        print(f"Submitting to: {submit_url}")
        print(f"Payload: {json.dumps(payload, indent=2)}")
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as http_client:
                response = await http_client.post(submit_url, json=payload)
                result = response.json()
                print(f"Submit response: {json.dumps(result, indent=2)}")
                return result
        except Exception as e:
            print(f"Submit error: {e}")
            return {"correct": False, "reason": str(e)}

@app.route('/quiz', methods=['POST'])
def handle_quiz():
    """Main endpoint for quiz tasks"""
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({"error": "Invalid JSON"}), 400
        
        if data.get('secret') != SECRET:
            return jsonify({"error": "Invalid secret"}), 403
        
        if data.get('email') != EMAIL:
            return jsonify({"error": "Invalid email"}), 403
        
        quiz_url = data.get('url')
        if not quiz_url:
            return jsonify({"error": "Missing quiz URL"}), 400
        
        print(f"\n{'='*60}")
        print(f"NEW QUIZ REQUEST")
        print(f"URL: {quiz_url}")
        print(f"Time: {datetime.now().isoformat()}")
        print(f"{'='*60}\n")
        
        # Solve quiz chain
        solver = QuizSolver(EMAIL, SECRET)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            results = loop.run_until_complete(solver.solve_quiz_chain(quiz_url))
            return jsonify({
                "status": "completed",
                "results": results,
                "timestamp": datetime.now().isoformat()
            }), 200
        finally:
            loop.close()
        
    except json.JSONDecodeError:
        return jsonify({"error": "Invalid JSON"}), 400
    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "email": EMAIL,
        "timestamp": datetime.now().isoformat()
    }), 200

@app.route('/', methods=['GET'])
def home():
    """Home endpoint"""
    return jsonify({
        "service": "LLM Quiz Solver",
        "student": "Gautham Venkatesh",
        "email": EMAIL,
        "endpoints": {
            "quiz": "/quiz (POST)",
            "health": "/health (GET)"
        }
    }), 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"Starting server on port {port}...")
    print(f"Email: {EMAIL}")
    print(f"OpenAI API Key: {'✓ Set' if OPENAI_API_KEY else '✗ Missing'}")
    print(f"Secret: {'✓ Set' if SECRET else '✗ Missing'}")
    app.run(host='0.0.0.0', port=port, debug=False)