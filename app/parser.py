"""
Transcript Parser - Parses transcript files (PDF/image) to JSON structure
Adapted for Technion grade sheet format
Uses Gemini Vision API for accurate Hebrew text recognition
"""
import re
import logging
from typing import Dict, List, Optional
from PIL import Image
import pytesseract
from pdf2image import convert_from_path
import io
import base64

# Setup logging first
logger = logging.getLogger(__name__)

# Try to import Google Generative AI (Gemini)
try:
    import google.generativeai as genai
    HAS_GEMINI = True
    logger.info("✅ Successfully imported google.generativeai")
except ImportError as e:
    HAS_GEMINI = False
    logger.error(f"❌ Failed to import google.generativeai: {e}")
    logger.error("   Please install: pip install google-generativeai")

from app.models import TranscriptData, UserBase, CourseBase


class TranscriptParser:
    """
    Parser for Hebrew transcript files (Technion format)
    Supports PDF and image formats
    Uses Vision API for best accuracy with Hebrew text
    """
    
    def __init__(self, gemini_api_key: Optional[str] = None):
        # Setup Gemini if API key provided
        self.gemini_api_key = gemini_api_key
        self.gemini_model = None
        
        if gemini_api_key and HAS_GEMINI:
            try:
                logger.info(f"Configuring Gemini with API key (first 10 chars: {gemini_api_key[:10]}...)")
                genai.configure(api_key=gemini_api_key)
                logger.info("✅ Gemini configured (skipping test to save quota)")
                
                # Use Gemini Flash models (free tier: 20 requests/day)
                # Try models in order of preference (newest first)
                model_names_to_try = [
                    'models/gemini-2.0-flash-exp',  # Latest Flash model
                    'models/gemini-2.0-flash',      # Stable Flash model
                    'models/gemini-2.0-flash-001',  # Flash model variant
                    'models/gemini-1.5-flash',      # Older Flash model (fallback)
                    'models/gemini-2.5-flash',      # If available
                ]
                self.gemini_model = None
                for model_name in model_names_to_try:
                    try:
                        logger.info(f"Trying model: {model_name}")
                        self.gemini_model = genai.GenerativeModel(model_name)
                        logger.info(f"✅ Successfully initialized model: {model_name}")
                        break
                    except Exception as model_error:
                        logger.warning(f"Model {model_name} failed: {model_error}")
                        continue
                if not self.gemini_model:
                    raise Exception("No working Gemini model found")
            except Exception as e:
                logger.error(f"Failed to initialize Gemini: {e}")
                import traceback
                logger.error(traceback.format_exc())
                self.gemini_model = None
        else:
            if not gemini_api_key:
                logger.warning("Gemini API key not provided - will use regex fallback")
            else:
                logger.warning("Gemini library not available (HAS_GEMINI=False) - will use regex fallback")
        
        if self.gemini_model:
            logger.info(f"=== GEMINI MODEL INITIALIZED SUCCESSFULLY ===")
        else:
            logger.warning(f"=== GEMINI MODEL NOT INITIALIZED (gemini_api_key={bool(gemini_api_key)}, HAS_GEMINI={HAS_GEMINI}) ===")
    
    def parse_pdf(self, file_path: str) -> TranscriptData:
        """
        Parse PDF transcript file using Gemini Vision API for best Hebrew text recognition
        Falls back to text extraction + Gemini text parsing if images can't be created
        """
        logger.info(f"=== parse_pdf called, gemini_model={self.gemini_model is not None} ===")
        
        # Try to convert PDF to images (requires poppler)
        images = None
        try:
            images = convert_from_path(file_path, dpi=300)
            logger.info(f"Converted PDF to {len(images)} images")
        except Exception as e:
            logger.warning(f"Could not convert PDF to images (poppler may not be installed): {e}")
            logger.info("Falling back to text extraction + Gemini")
            # Fallback to text extraction
            return self._parse_pdf_with_text_extraction(file_path)
        
        if not images:
            logger.warning("No images extracted from PDF, falling back to text extraction")
            return self._parse_pdf_with_text_extraction(file_path)
        
        # Try Vision API first (best for Hebrew - reads text directly from images)
        logger.info(f"=== Checking gemini_model for Vision: {self.gemini_model is not None} ===")
        if self.gemini_model:
            try:
                logger.info("=== USING GEMINI VISION API (BEST FOR HEBREW) ===")
                result = self._parse_with_vision(images)
                logger.info(f"=== VISION PARSING SUCCESSFUL! Found {len(result.courses)} courses ===")
                return result
            except Exception as e:
                logger.error(f"Vision parsing failed: {e}")
                import traceback
                logger.error(traceback.format_exc())
                logger.warning("Falling back to text extraction")
                return self._parse_pdf_with_text_extraction(file_path)
        
        # Fallback to text extraction if Gemini not available
        logger.warning("=== Gemini model not available - falling back to text extraction ===")
        return self._parse_pdf_with_text_extraction(file_path)
    
    def _fix_rtl_text(self, text: str) -> str:
        """
        Fix RTL text direction issues in extracted text
        Handles cases where Hebrew text appears reversed
        """
        if not text or not isinstance(text, str):
            return ""
        
        lines = text.split('\n')
        fixed_lines = []
        
        for line in lines:
            if not line or not isinstance(line, str):
                fixed_lines.append("")
                continue
                
            # Check if line contains Hebrew characters
            has_hebrew = bool(re.search(r'[א-ת]', line))
            
            if has_hebrew:
                # Split line into words
                words = line.split()
                # Reverse words if they appear in wrong order
                # (Simple heuristic: if line starts with numbers/English, might be reversed)
                if words and re.match(r'^[\d\w]+', words[0]):
                    # Might be reversed, try reversing
                    words = words[::-1]
                    line = ' '.join(words)
            
            fixed_lines.append(line)
        
        return '\n'.join(fixed_lines)
    
    def _parse_pdf_with_text_extraction(self, file_path: str) -> TranscriptData:
        """
        Parse PDF by extracting text first, then using Gemini to parse the text
        This is a fallback when poppler is not available
        """
        import PyPDF2
        import pdfplumber
        from pdfminer.high_level import extract_text as pdfminer_extract_text
        from pdfminer.layout import LAParams
        
        all_text = ""
        
        # Try multiple text extraction methods
        # Method 1: pdfminer (best for Hebrew)
        try:
            laparams = LAParams(
                line_margin=0.5,
                word_margin=0.1,
                char_margin=2.0,
                boxes_flow=0.5
            )
            extracted_text = pdfminer_extract_text(file_path, laparams=laparams)
            if extracted_text and isinstance(extracted_text, str) and len(extracted_text.strip()) > 100:
                all_text = extracted_text
                logger.info("Extracted text using pdfminer")
        except Exception as e:
            logger.warning(f"pdfminer extraction failed: {e}")
        
        # Method 2: pdfplumber
        if not all_text or len(all_text.strip()) < 100:
            try:
                with pdfplumber.open(file_path) as pdf:
                    extracted_text = ""
                    for page in pdf.pages:
                        page_text = page.extract_text()
                        if page_text and isinstance(page_text, str):
                            extracted_text += page_text + "\n"
                    if extracted_text and len(extracted_text.strip()) >= 100:
                        all_text = extracted_text
                        logger.info("Extracted text using pdfplumber")
            except Exception as e:
                logger.warning(f"pdfplumber extraction failed: {e}")
        
        # Method 3: PyPDF2
        if not all_text or len(all_text.strip()) < 100:
            try:
                with open(file_path, 'rb') as file:
                    pdf_reader = PyPDF2.PdfReader(file)
                    extracted_text = ""
                    for page in pdf_reader.pages:
                        page_text = page.extract_text()
                        if page_text and isinstance(page_text, str):
                            extracted_text += page_text + "\n"
                    if extracted_text and len(extracted_text.strip()) >= 100:
                        all_text = extracted_text
                        logger.info("Extracted text using PyPDF2")
            except Exception as e:
                logger.warning(f"PyPDF2 extraction failed: {e}")
        
        if not all_text or len(all_text.strip()) < 50:
            logger.error("Could not extract text from PDF using any method")
            raise ValueError("Could not extract text from PDF using any method")
        
        logger.info(f"Extracted {len(all_text)} characters of text from PDF")
        logger.info(f"First 500 chars: {all_text[:500]}")
        
        # Use Gemini to parse the extracted text
        logger.info(f"=== CHECKING GEMINI: gemini_model={self.gemini_model is not None}, type={type(self.gemini_model)} ===")
        if self.gemini_model:
            try:
                logger.info("=== USING GEMINI TO PARSE EXTRACTED TEXT ===")
                result = self._parse_text_with_gemini(all_text)
                logger.info(f"Gemini parsing successful, found {len(result.courses)} courses")
                return result
            except Exception as e:
                logger.error(f"Gemini text parsing failed: {e}")
                import traceback
                logger.error(traceback.format_exc())
                logger.warning("Falling back to regex extraction")
        else:
            logger.warning(f"=== Gemini model not available! gemini_model={self.gemini_model}, using regex extraction ===")
        
        # Final fallback: regex extraction
        logger.info("Using regex extraction fallback")
        # Fix RTL text for regex (regex patterns expect correct direction)
        fixed_text = self._fix_rtl_text(all_text)
        student_info = self._extract_student_info_regex(fixed_text)
        courses = self._extract_courses_regex(fixed_text)
        logger.info(f"Regex extraction found {len(courses)} courses")
        
        return TranscriptData(
            student_info=UserBase(**student_info),
            courses=[CourseBase(**course) for course in courses],
            metadata={
                "parsing_method": "text_extraction_regex",
                "total_courses": len(courses)
            }
        )
    
    def _parse_text_with_gemini(self, text: str) -> TranscriptData:
        """
        Parse extracted text using Gemini (without images)
        """
        import json
        import time
        
        prompt = f"""אתה מנתח גיליון ציונים מטעם הטכניון. 

חשוב מאוד: 
1. תחילה חלץ את פרטי הסטודנט מהחלק העליון של הגיליון (הכותרות והפרטים בראש המסמך)
2. אחר כך חלץ את כל הקורסים מהטבלה/רשימת הקורסים

חלץ את המידע בדיוק כפי שהוא מופיע בטקסט - אל תשנה, אל תתקן, אל תערוך שום טקסט!
אם כתוב 'מעין גלמידי' תחזיר 'מעין גלמידי' (לא 'גלמידי מעין' ולא 'ויעמ ידימלג').

טקסט הגיליון:
{text}

חלץ JSON:
{{
    "student_info": {{
        "name": "שם הסטודנט בדיוק כפי שמופיע (ללא 'תעודת ציונים של' או 'ת.ז.')",
        "id_number": "מספר תעודת זהות (9 ספרות)",
        "faculty": "שם הפקולטה בדיוק כפי שמופיע (ללא 'בפקולטה')",
        "study_track": "מסלול הלימודים בדיוק כפי שמופיע (ללא 'לתואר' או 'מוסמך למדעים')",
        "cumulative_average": מספר הממוצע המצטבר,
        "success_rate": מספר אחוזי הצלחה או null,
        "current_semester": "סמסטר נוכחי או null",
        "current_year": מספר השנה או null
    }},
    "courses": [
        {{
            "course_name": "שם הקורס בדיוק כפי שמופיע",
            "course_number": "מספר קורס",
            "credit_points": מספר נקודות,
            "grade": מספר ציון או null,
            "letter_grade": "ציון אות או null",
            "semester": "סמסטר",
            "year": מספר שנה,
            "notes": "הערות (או null)",
            "is_passed": true/false,
            "retake_count": 0
        }}
    ],
    "summary": {{
        "total_credit_points": null,
        "completed_courses_count": null,
        "total_courses_count": null
    }}
}}

הוראות מפורטות:
- student_info: חלץ מהחלק העליון של הגיליון (הכותרות)
  * name: מהטקסט "תעודת ציונים של [שם] ת.ז.: [מספר]" - רק את השם. אם כתוב 'מעין גלמידי' תחזיר 'מעין גלמידי' (לא 'גלמידי מעין' ולא 'ויעמ ידימלג').
  * id_number: מספר תעודת זהות (9 ספרות)
  * faculty: מהטקסט "בפקולטה [שם]" - רק את השם בלי "בפקולטה"
  * study_track: מהטקסט "לתואר מוסמך למדעים ב[מסלול]" או "מסלול: [מסלול]" - רק את המסלול
  * cumulative_average: ממוצע מצטבר (מספר, למשל 90.7)
  * success_rate: אחוזי הצלחה (מספר או null, למשל 85.5)
- courses: חלץ את כל הקורסים מהטבלה/רשימה - כל קורס עם כל הפרטים
- summary: כל השדות צריכים להיות null (אל תחשב שום דבר)

חזור רק JSON."""

        try:
            start_time = time.time()
            logger.info(f"=== CALLING GEMINI API FOR TEXT PARSING ===")
            logger.info(f"Text length: {len(text)} characters")
            response = self.gemini_model.generate_content(prompt)
            elapsed_time = time.time() - start_time
            logger.info(f"=== GOT RESPONSE FROM GEMINI (took {elapsed_time:.2f} seconds) ===")
            response_text = response.text.strip()
        except Exception as api_error:
            # Check if it's a quota/rate limit error
            error_str = str(api_error).lower()
            if "quota" in error_str or "rate limit" in error_str or "resourceexhausted" in error_str or "429" in error_str:
                logger.error(f"❌ Gemini API quota exceeded: {api_error}")
                logger.warning("⚠️ Free tier limit reached (20 requests/day). Falling back to regex extraction.")
                logger.warning("   You can wait 24 hours or upgrade your API plan.")
                raise ValueError("Gemini API quota exceeded. Please wait 24 hours or use regex extraction.")
            else:
                # Other API errors - re-raise
                raise
            
            # Remove markdown code blocks if present
            if response_text.startswith('```'):
                response_text = re.sub(r'^```json\s*', '', response_text)
                response_text = re.sub(r'^```\s*', '', response_text)
                response_text = re.sub(r'```\s*$', '', response_text)
            
            # Parse JSON response
            logger.info(f"Parsing JSON response...")
            parsed_data = json.loads(response_text)
            logger.info(f"Parsed data keys: {parsed_data.keys()}")
            
            # Extract student info
            student_info = parsed_data.get('student_info', {})
            student_info_dict = {
                'name': student_info.get('name', 'לא זוהה'),
                'id_number': student_info.get('id_number', '000000000'),
                'faculty': student_info.get('faculty'),
                'study_track': student_info.get('study_track'),
                'cumulative_average': student_info.get('cumulative_average'),
                'success_rate': student_info.get('success_rate'),
                'current_semester': student_info.get('current_semester'),
                'current_year': student_info.get('current_year'),
            }
            
            # Extract courses
            courses_data = parsed_data.get('courses', [])
            courses = []
            for course in courses_data:
                courses.append({
                    'course_name': course.get('course_name', ''),
                    'course_number': course.get('course_number'),
                    'credit_points': course.get('credit_points'),
                    'grade': course.get('grade'),
                    'letter_grade': course.get('letter_grade'),
                    'semester': course.get('semester'),
                    'year': course.get('year'),
                    'notes': course.get('notes'),
                    'is_passed': course.get('is_passed', True),
                    'retake_count': course.get('retake_count', 0),
                })
            
            # Extract summary if available
            summary = parsed_data.get('summary', {})
            
            logger.info(f"Gemini parsed: {len(courses)} courses, student: {student_info_dict.get('name')}")
            
            return TranscriptData(
                student_info=UserBase(**student_info_dict),
                courses=[CourseBase(**course) for course in courses],
                metadata={
                    "parsing_method": "gemini_text",
                    "total_courses": len(courses),
                    "completed_courses_count": summary.get('completed_courses_count'),
                    "total_credit_points": summary.get('total_credit_points'),
                    **summary
                }
            )
            
        except Exception as e:
            logger.error(f"Error in Gemini text parsing: {e}")
            import traceback
            logger.error(traceback.format_exc())
            raise
    
    def _parse_with_vision(self, images: List[Image.Image]) -> TranscriptData:
        """
        Parse using Gemini Vision API - analyzes images directly
        This is the most accurate method for Hebrew text
        """
        all_data = {
            "student_info": None,
            "courses": []
        }
        
        for i, image in enumerate(images):
            logger.info(f"Processing page {i+1}/{len(images)} with Vision API")
            
            page_data = self._parse_image_with_gemini(image, page_num=i+1)
            
            # Merge results
            if page_data:
                logger.info(f"Page {i+1} returned data: student_info={page_data.get('student_info') is not None}, courses={len(page_data.get('courses', []))}")
                if page_data.get("student_info") and not all_data["student_info"]:
                    all_data["student_info"] = page_data["student_info"]
                    logger.info(f"Set student_info from page {i+1}: {all_data['student_info']}")
                
                if page_data.get("courses"):
                    all_data["courses"].extend(page_data["courses"])
            else:
                logger.warning(f"Page {i+1} returned no data")
        
        # Validate we got data
        logger.info(f"Final data: student_info={all_data['student_info'] is not None}, courses={len(all_data['courses'])}")
        if not all_data["student_info"]:
            logger.warning("No student_info found in any page, using defaults")
            all_data["student_info"] = {
                "name": "לא זוהה",
                "id_number": "000000000"
            }
        
        return TranscriptData(
            student_info=UserBase(**all_data["student_info"]),
            courses=[CourseBase(**course) for course in all_data["courses"]],
            metadata={
                "parsing_method": "gemini_vision",
                "total_courses": len(all_data["courses"]),
                "pages_processed": len(images)
            }
        )
    
    def _parse_image_with_gemini(self, image: Image.Image, page_num: int) -> Optional[Dict]:
        """
        Parse a single page image using Gemini Vision API
        """
        prompt = """אתה מנתח תמונה של גיליון ציונים מהטכניון בעברית.

חשוב מאוד: 
1. תחילה חלץ את פרטי הסטודנט מהחלק העליון של הגיליון (הכותרות והפרטים בראש המסמך)
2. אחר כך חלץ את כל הקורסים מהטבלה/רשימת הקורסים

חלץ את המידע בדיוק כפי שהוא מופיע בתמונה - אל תשנה, אל תתקן, אל תערוך שום טקסט!
קרא את הטקסט בעברית בדיוק כמו שהוא מופיע בתמונה - Vision API קורא טקסט בעברית בצורה נכונה.

החזר JSON בפורמט הבא (רק JSON, ללא טקסט נוסף):
{
    "student_info": {
        "name": "שם הסטודנט בדיוק כפי שמופיע (ללא 'תעודת ציונים של' או 'ת.ז.')",
        "id_number": "מספר תעודת זהות (9 ספרות)",
        "faculty": "שם הפקולטה בדיוק כפי שמופיע (ללא 'בפקולטה')",
        "study_track": "מסלול הלימודים בדיוק כפי שמופיע (ללא 'לתואר' או 'מוסמך למדעים')",
        "cumulative_average": מספר הממוצע המצטבר,
        "success_rate": מספר אחוזי הצלחה או null,
        "current_semester": "סמסטר נוכחי או null",
        "current_year": מספר השנה או null
    },
    "courses": [
        {
            "course_name": "שם הקורס בדיוק כפי שמופיע",
            "course_number": "מספר קורס",
            "credit_points": מספר נקודות,
            "grade": מספר ציון או null,
            "letter_grade": "ציון אות או null",
            "semester": "סמסטר",
            "year": מספר שנה,
            "notes": "הערות (או null)",
            "is_passed": true/false,
            "retake_count": 0
        }
    ]
}

הוראות מפורטות:
- student_info: חלץ מהחלק העליון של הגיליון (הכותרות)
  * name: מהטקסט "תעודת ציונים של [שם] ת.ז.: [מספר]" - רק את השם
  * id_number: מספר תעודת זהות (9 ספרות)
  * faculty: מהטקסט "בפקולטה [שם]" - רק את השם בלי "בפקולטה"
  * study_track: מהטקסט "לתואר מוסמך למדעים ב[מסלול]" או "מסלול: [מסלול]" - רק את המסלול
  * cumulative_average: ממוצע מצטבר (מספר, למשל 90.7) - חלץ מהטקסט "ממוצע מצטבר" או "בממוצע ציונים"
  * success_rate: אחוזי הצלחה (מספר או null, למשל 85.5) - חלץ מהטקסט "אחוזי הצלחה" או "שיעור הצלחות"
- courses: חלץ את כל הקורסים מהטבלה/רשימה - כל קורס עם כל הפרטים

אם פרטי הסטודנט לא מופיעים בעמוד זה, החזר null ב-student_info."""

        try:
            # Generate response with image
            response = self.gemini_model.generate_content(
                [prompt, image],
                generation_config={
                    "temperature": 0.1,  # Low temperature for accuracy
                    "max_output_tokens": 8192,
                }
            )
            
            response_text = response.text.strip()
            
            # Clean markdown code blocks
            if response_text.startswith('```'):
                response_text = re.sub(r'^```json\s*', '', response_text)
                response_text = re.sub(r'^```\s*', '', response_text)
                response_text = re.sub(r'```\s*$', '', response_text)
                response_text = response_text.strip()
            
            # Parse JSON
            import json
            data = json.loads(response_text)
            
            logger.info(f"Page {page_num}: Found {len(data.get('courses', []))} courses")
            
            # Clean student info if present
            if data.get('student_info'):
                info = data['student_info']
                # Ensure we have all required fields
                if not info.get('name'):
                    info['name'] = 'לא זוהה'
                if not info.get('id_number'):
                    info['id_number'] = '000000000'
            
            return data
            
        except Exception as e:
            logger.error(f"Failed to parse page {page_num} with Vision API: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None
    
    def _parse_with_ocr(self, images: List[Image.Image]) -> TranscriptData:
        """
        Fallback OCR parsing when Vision API is not available
        """
        all_text = ""
        
        for i, image in enumerate(images):
            logger.info(f"OCR processing page {i+1}/{len(images)}")
            
            try:
                # Use Hebrew OCR
                page_text = pytesseract.image_to_string(
                    image,
                    lang='heb',
                    config='--psm 6 --oem 3'
                )
                all_text += page_text + "\n"
            except Exception as e:
                logger.warning(f"OCR failed for page {i+1}: {e}")
        
        if not all_text or len(all_text.strip()) < 50:
            raise ValueError("OCR extraction failed - no text found")
        
        # Extract info using regex (basic fallback)
        student_info = self._extract_student_info_regex(all_text)
        courses = self._extract_courses_regex(all_text)
        
        return TranscriptData(
            student_info=UserBase(**student_info),
            courses=[CourseBase(**course) for course in courses],
            metadata={
                "parsing_method": "ocr_fallback",
                "total_courses": len(courses)
            }
        )
    
    def _extract_student_info_regex(self, text: str) -> Dict:
        """
        Extract student info using regex patterns (fallback method)
        """
        info = {
            'name': 'לא זוהה',
            'id_number': '000000000'
        }
        
        # Extract ID
        id_match = re.search(r'ת\.?ז\.?[:\s]*(\d{9})', text)
        if id_match:
            info['id_number'] = id_match.group(1)
        
        # Extract name
        name_match = re.search(r'תעודת ציונים של\s+([א-ת\s]{2,40}?)\s+ת\.?ז\.?', text)
        if name_match:
            info['name'] = name_match.group(1).strip()
        
        # Extract faculty
        faculty_match = re.search(r'בפקולטה\s+([א-ת\s]+?)(?:\n|לתואר)', text)
        if faculty_match:
            info['faculty'] = faculty_match.group(1).strip()
        
        # Extract study track
        track_match = re.search(r'לתואר.*?ב([א-ת\s]+?)(?:\n|ממוצע)', text)
        if track_match:
            info['study_track'] = track_match.group(1).strip()
        
        # Extract average
        avg_match = re.search(r'בממוצע ציונים\s+([\d.]+)', text)
        if avg_match:
            try:
                info['cumulative_average'] = float(avg_match.group(1))
            except ValueError:
                pass
        
        return info
    
    def _extract_courses_regex(self, text: str) -> List[Dict]:
        """
        Extract courses using regex patterns (fallback method)
        """
        courses = []
        lines = text.split('\n')
        
        current_semester = None
        current_year = None
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Detect semester
            semester_match = re.search(r'(חורף|אביב|קיץ)\s+תשפ["\']?[א-ה]', line)
            if semester_match:
                current_semester = semester_match.group(1)
                year_match = re.search(r'(\d{4})', line)
                if year_match:
                    current_year = int(year_match.group(1))
                continue
            
            # Look for course number
            course_num_match = re.search(r'\b(\d{6,8})\b', line)
            if not course_num_match:
                continue
            
            course_number = course_num_match.group(1)
            
            # Extract course name (Hebrew text)
            name_match = re.search(r'[א-ת][\s\sא-ת]+', line)
            course_name = name_match.group(0).strip() if name_match else ""
            
            # Extract grade
            grade_match = re.search(r'\b(\d{2,3})\b', line)
            grade = None
            if grade_match:
                grade_val = int(grade_match.group(1))
                if 0 <= grade_val <= 100:
                    grade = float(grade_val)
            
            # Extract credit points
            credit_match = re.search(r'\b(\d+\.5|\d+)\b', line)
            credit_points = None
            if credit_match:
                try:
                    credit_val = float(credit_match.group(1))
                    if 0 <= credit_val <= 10:
                        credit_points = credit_val
                except ValueError:
                    pass
            
            if course_name or course_number:
                courses.append({
                    'course_number': course_number,
                    'course_name': course_name,
                    'credit_points': credit_points,
                    'grade': grade,
                    'semester': current_semester,
                    'year': current_year,
                    'notes': None,
                    'is_passed': True,
                    'retake_count': 0
                })
        
        return courses
    
    def parse_image(self, file_path: str) -> TranscriptData:
        """
        Parse image file using Vision API
        """
        try:
            image = Image.open(file_path)
            return self._parse_with_vision([image])
        except Exception as e:
            raise ValueError(f"Error parsing image: {str(e)}")
    
    def parse_file(self, file_path: str, file_type: str) -> TranscriptData:
        """
        Main entry point - parse file based on type
        """
        if file_type.startswith('image/'):
            return self.parse_image(file_path)
        elif file_type == 'application/pdf':
            return self.parse_pdf(file_path)
        else:
            raise ValueError(f"Unsupported file type: {file_type}")


def manual_entry_to_json(user_data: dict, courses_data: list) -> TranscriptData:
    """
    Helper function to convert manual entry form data to JSON structure
    """
    student_info = UserBase(**user_data)
    courses = [CourseBase(**course) for course in courses_data]
    
    return TranscriptData(
        student_info=student_info,
        courses=courses
    )