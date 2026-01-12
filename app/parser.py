"""
Transcript Parser - Parses transcript files (PDF/image) to JSON structure
Adapted for Technion grade sheet format
Uses multiple libraries for better Hebrew text extraction
"""
import re
from typing import Dict, List, Optional, Tuple
from PIL import Image
import pytesseract
from pdf2image import convert_from_path
import PyPDF2
import pdfplumber
from pdfminer.high_level import extract_text as pdfminer_extract_text
from pdfminer.layout import LAParams
import io
from app.models import TranscriptData, UserBase, CourseBase


class TranscriptParser:
    """
    Parser for Hebrew transcript files (Technion format)
    Supports PDF and image formats
    """
    
    def __init__(self):
        # Patterns for Technion grade sheet format
        self.patterns = {
            'id_number': r'ת\.?ז\.?[:\s]*(\d{9})',
            'name': r'^([א-ת\s]+?)\s+ת\.?ז\.?',
            'faculty': r'פקולטה[:\s]*([א-ת\s]+?)(?:לתואר|$)',
            'study_track': r'לתואר[:\s]*([א-ת\s]+?)(?:$|\n|ממוצע)',
            'cumulative_average': r'ממוצע מצטבר[:\s]*([\d.]+)',
            'success_rate': r'שיעור הצלחות מצטבר[:\s]*([\d.]+)',
            'course_number': r'(\d{6,8})',  # Course numbers are 6-8 digits
            'date': r'נכון לתאריך[:\s]*(\d{1,2}\.\d{1,2}\.\d{4})',
        }
    
    def parse_pdf(self, file_path: str) -> TranscriptData:
        """
        Parse PDF transcript file using multiple methods for better Hebrew text extraction
        Tries: pdfminer (best for Hebrew) -> pdfplumber (tables) -> PyPDF2 -> OCR
        """
        all_text = ""
        all_tables = []
        parsing_method = "unknown"
        
        # Method 1: Try pdfminer.six first (best for Hebrew RTL text)
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
                parsing_method = "pdfminer"
                # Fix RTL text direction issues
                all_text = self._fix_rtl_text(all_text)
        except Exception as e:
            all_text = None
        
        # Method 2: Try pdfplumber for tables (if pdfminer didn't work well)
        if not all_text or (isinstance(all_text, str) and len(all_text.strip()) < 100):
            try:
                with pdfplumber.open(file_path) as pdf:
                    extracted_text = ""
                    for page_num, page in enumerate(pdf.pages):
                        # Extract text
                        page_text = page.extract_text()
                        if page_text and isinstance(page_text, str):
                            extracted_text += page_text + "\n"
                        
                        # Extract tables
                        tables = page.extract_tables()
                        if tables:
                            all_tables.extend(tables)
                    
                    if extracted_text and len(extracted_text.strip()) >= 100:
                        all_text = extracted_text
                        all_text = self._fix_rtl_text(all_text)
                        parsing_method = "pdfplumber"
            except Exception as e:
                pass
        
        # Method 3: Fallback to PyPDF2
        if not all_text or (isinstance(all_text, str) and len(all_text.strip()) < 100):
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
                        all_text = self._fix_rtl_text(all_text)
                        parsing_method = "pypdf2"
            except Exception as e:
                pass
        
        # Method 4: OCR as last resort
        if not all_text or (isinstance(all_text, str) and len(all_text.strip()) < 100):
            try:
                images = convert_from_path(file_path, dpi=300)
                extracted_text = ""
                for image in images:
                    # Use Hebrew OCR with better settings
                    ocr_text = pytesseract.image_to_string(
                        image, 
                        lang='heb',
                        config='--psm 6 -c preserve_interword_spaces=1'
                    )
                    if ocr_text and isinstance(ocr_text, str):
                        extracted_text += ocr_text + "\n"
                
                if extracted_text and len(extracted_text.strip()) >= 50:
                    all_text = extracted_text
                    all_text = self._fix_rtl_text(all_text)
                    parsing_method = "ocr"
            except Exception as e:
                pass
        
        # Final check - ensure we have valid text
        if not all_text or not isinstance(all_text, str) or len(all_text.strip()) < 50:
            raise ValueError("Could not extract text from PDF using any method")
        
        # Extract student info from text
        student_info = self._extract_student_info(all_text)
        
        # Parse courses from tables (if available) or text
        courses_from_tables = []
        if all_tables:
            courses_from_tables = self._extract_courses_from_tables(all_tables)
        
        # Also try text-based extraction
        courses_from_text = self._extract_courses(all_text)
        
        # Combine and deduplicate courses (prefer table-based)
        all_courses = courses_from_tables.copy()
        existing_course_numbers = {c.get('course_number') for c in all_courses if c.get('course_number')}
        for course in courses_from_text:
            if course.get('course_number') not in existing_course_numbers:
                all_courses.append(course)
        
        return TranscriptData(
            student_info=UserBase(**student_info),
            courses=[CourseBase(**course) for course in all_courses],
            metadata={
                "source_text_length": len(all_text),
                "total_courses": len(all_courses),
                "tables_found": len(all_tables),
                "parsing_method": parsing_method
            }
        )
    
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
    
    def parse_image(self, file_path: str) -> TranscriptData:
        """
        Parse image transcript file with improved Hebrew OCR
        """
        try:
            image = Image.open(file_path)
            # Use better OCR settings for Hebrew
            text = pytesseract.image_to_string(
                image, 
                lang='heb',
                config='--psm 6 -c preserve_interword_spaces=1'
            )
            # Fix RTL text issues
            text = self._fix_rtl_text(text)
            return self._parse_text(text)
        except Exception as e:
            raise ValueError(f"Error parsing image: {str(e)}")
    
    def _parse_text(self, text: str) -> TranscriptData:
        """
        Parse extracted text to structured data
        """
        # Extract student info
        student_info = self._extract_student_info(text)
        
        # Extract courses
        courses = self._extract_courses(text)
        
        return TranscriptData(
            student_info=UserBase(**student_info),
            courses=[CourseBase(**course) for course in courses],
            metadata={"source_text_length": len(text), "total_courses": len(courses)}
        )
    
    def _extract_student_info(self, text: str) -> Dict:
        """
        Extract student information from text
        Handles multiple formats:
        - Format 1: "נועם שמש ת.ז.: 206879033"
        - Format 2: "תעודת ציונים של מעין גלמידי ת.ז.: 206691420"
        - Format 3: "הלומדת" / "הלומד"
        """
        info = {}
        
        # Extract ID number - try multiple patterns
        id_match = re.search(self.patterns['id_number'], text)
        if not id_match:
            # Try alternative patterns
            id_match = re.search(r'ת\.?ז\.?[:\s]*(\d{9})', text, re.IGNORECASE)
        if not id_match:
            id_match = re.search(r'(\d{9})', text)
            # Only use if it's near ת.ז.
            if id_match:
                context = text[max(0, id_match.start()-20):id_match.end()+20]
                if 'ת.ז' not in context and 'תז' not in context:
                    id_match = None
        
        if id_match:
            info['id_number'] = id_match.group(1)
        else:
            # Default fallback - required field
            info['id_number'] = '000000000'
        
        # Extract name - try multiple patterns (including reversed text)
        # Format 1: "תעודת ציונים של מעין גלמידי ת.ז.: 206691420"
        name_match = re.search(r'תעודת ציונים של\s+([א-ת\s]{2,30}?)\s+ת\.?ז\.?[:\s]*\d{9}', text)
        if not name_match:
            # Format 1 reversed: "206691420 :ת.ז. ילמדג ןיעמ לש םינוצ תדועת"
            name_match = re.search(r'\d{9}\s*[:\s]*ת\.?ז\.?\s+([א-ת\s]{2,30}?)\s+של\s+תעודת\s+ציונים', text)
        if not name_match:
            # Format 2: "נועם שמש ת.ז.: 206879033"
            name_match = re.search(r'([א-ת\s]{2,30}?)\s+ת\.?ז\.?[:\s]*\d{9}', text)
        if not name_match:
            # Format 2 reversed: "206879033 :ת.ז. שמש נעום"
            name_match = re.search(r'\d{9}\s*[:\s]*ת\.?ז\.?\s+([א-ת\s]{2,30}?)', text)
        if not name_match:
            # Format 3: Try alternative pattern
            name_match = re.search(r'^([א-ת\s]{2,30}?)\s+ת\.?ז\.?', text, re.MULTILINE)
        if not name_match:
            # Try to find name before ID number
            if 'id_number' in info and info['id_number'] != '000000000':
                id_pos = text.find(info['id_number'])
                if id_pos > 0:
                    before_id = text[max(0, id_pos-60):id_pos]
                    # Look for Hebrew name before ID
                    name_match2 = re.search(r'([א-ת\s]{2,30}?)\s*ת\.?ז\.?', before_id)
                    if name_match2:
                        name_match = name_match2
                # Also try after ID (for reversed text)
                if not name_match and id_pos >= 0:
                    after_id = text[id_pos+len(info['id_number']):id_pos+len(info['id_number'])+60]
                    name_match2 = re.search(r'ת\.?ז\.?\s*([א-ת\s]{2,30}?)', after_id)
                    if name_match2:
                        name_match = name_match2
        
        if name_match:
            name_text = name_match.group(1)
            if name_text:
                name_text = name_text.strip()
                # Clean up name - remove common prefixes
                name_text = re.sub(r'^גיליון[:\s]*', '', name_text)
                name_text = re.sub(r'^תעודת ציונים של\s*', '', name_text)
                name_text = re.sub(r'\s+של\s+תעודת\s+ציונים$', '', name_text)
                # Reverse if it looks reversed (starts with Hebrew but has wrong order)
                if re.match(r'^[א-ת]', name_text) and len(name_text.split()) > 1:
                    # Check if words are in wrong order (simple heuristic)
                    words = name_text.split()
                    if len(words) == 2:
                        # Try reversing if first word looks like last name
                        if len(words[0]) < len(words[1]):
                            name_text = ' '.join(reversed(words))
                info['name'] = name_text
            else:
                info['name'] = 'לא זוהה'
        else:
            # Default fallback - required field
            info['name'] = 'לא זוהה'
        
        # Extract faculty and study track
        # Format 1: "פקולטה: מדעי הנתונים וההחלטות לתואר: מוסמך למדעים בהנדסת נתונים ומידע"
        # Format 2: "בפקולטה מדעי הנתונים וההחלטות" (separate line)
        # Format 3: "לתואר מוסמך למדעים בהנדסת נתונים ומידע" (separate line)
        
        # Try format with "בפקולטה" prefix
        faculty_match = re.search(r'בפקולטה\s+([א-ת\s]+?)(?:\n|לתואר|ממוצע|$)', text)
        if faculty_match:
            faculty_text = faculty_match.group(1)
            if faculty_text:
                info['faculty'] = faculty_text.strip()
        
        # Also try "פקולטה:" format
        if not info.get('faculty'):
            faculty_line_match = re.search(r'פקולטה[:\s]*([^\n]+?)(?:\n|ממוצע|$)', text)
            if faculty_line_match:
                faculty_line = faculty_line_match.group(1).strip()
                # Clean up - remove common unwanted text
                faculty_line = re.sub(r'^בפקולטה[:\s]*', '', faculty_line)
                
                # Split by "לתואר:"
                if 'לתואר' in faculty_line:
                    parts = re.split(r'לתואר[:\s]+', faculty_line, 1)
                    if len(parts) >= 2:
                        info['faculty'] = parts[0].strip()
                        # Take study track until next keyword or end of line
                        study_track_text = parts[1].strip()
                        # Stop at common keywords (but allow longer study track names)
                        study_track_text = re.split(r'[:\s]*(?:ממוצע|שיעור|נקודות|עמוד|\n|$)', study_track_text)[0]
                        info['study_track'] = study_track_text.strip()
                    else:
                        info['faculty'] = faculty_line.split('לתואר')[0].strip()
                else:
                    # No "לתואר" - just faculty
                    info['faculty'] = faculty_line.split('\n')[0].split('ממוצע')[0].strip()
        
        # Extract study track separately if not found yet
        if not info.get('study_track'):
            # Look for "לתואר:" in a separate line or context
            study_track_match = re.search(r'לתואר\s+([א-ת\s]{5,100}?)(?:\s|$|ממוצע|שיעור|נקודות|עמוד|\n|בפקולטה)', text)
            if study_track_match:
                study_track_text = study_track_match.group(1)
                if study_track_text:
                    study_track_text = study_track_text.strip()
                    # Clean up
                    study_track_text = re.sub(r'^בפקולטה[:\s]*', '', study_track_text)
                    info['study_track'] = study_track_text.strip()
        
        # Extract cumulative average - make sure it's cumulative, not semester average
        # Look for "ממוצע מצטבר" first (should appear multiple times - take the last one which is most up-to-date)
        cumulative_avg_matches = list(re.finditer(self.patterns['cumulative_average'], text))
        if cumulative_avg_matches:
            # Take the last match (most recent/up-to-date)
            avg_match = cumulative_avg_matches[-1]
            try:
                avg_value = float(avg_match.group(1))
                # Validate it's a reasonable average (0-100)
                if 0 <= avg_value <= 100:
                    info['cumulative_average'] = avg_value
            except ValueError:
                pass
        
        # Also try "ממוצע ציונים" (average grades) - used in some formats
        if not info.get('cumulative_average'):
            avg_grades_match = re.search(r'בממוצע ציונים\s+([\d.]+)', text)
            if not avg_grades_match:
                avg_grades_match = re.search(r'ממוצע ציונים[:\s]*([\d.]+)', text)
            if avg_grades_match:
                try:
                    avg_value = float(avg_grades_match.group(1))
                    if 0 <= avg_value <= 100:
                        info['cumulative_average'] = avg_value
                except ValueError:
                    pass
        
        # Also check for semester average to avoid confusion - but don't use it
        semester_avg_match = re.search(r'ממוצע סמסטר[:\s]*([\d.]+)', text)
        # We ignore semester average - only use cumulative
        
        # Extract success rate
        success_match = re.search(self.patterns['success_rate'], text)
        if success_match:
            try:
                info['success_rate'] = float(success_match.group(1))
            except ValueError:
                pass
        
        # Extract date (for current semester/year detection)
        date_match = re.search(self.patterns['date'], text)
        if date_match:
            # Could parse date to determine current semester/year
            pass
        
        return info
    
    def _extract_courses_from_tables(self, tables: List[List]) -> List[Dict]:
        """
        Extract courses from PDF tables using pdfplumber
        Handles different table formats in Technion grade sheets:
        - Format 1: [זיכויים, None, נקודות, ציון, מקצוע, מספר קורס]
        - Format 2: [ציון, נקודות, מקצוע, מספר קורס]
        - Format 3: [סמסטר/שנה, נקודות, מקצוע, מספר קורס]
        """
        courses = []
        current_semester = None
        current_year = None
        
        for table in tables:
            if not table or len(table) < 2:  # Need at least header + one row
                continue
            
            # Find header row - look for common headers
            header_row_idx = None
            for i, row in enumerate(table):
                if not row:
                    continue
                row_text = ' '.join([str(cell) for cell in row if cell])
                # Check if this row contains table headers
                if any(keyword in row_text for keyword in ['ציון', 'נקודות', 'מקצוע', 'זיכויים', 'תשפ']):
                    header_row_idx = i
                    break
            
            if header_row_idx is None:
                continue
            
            header = table[header_row_idx]
            
            # Find column indices by analyzing header
            course_name_col = None
            course_number_col = None
            credit_points_col = None
            grade_col = None
            
            for idx, cell in enumerate(header):
                if not cell:
                    continue
                cell_str = str(cell).strip()
                
                if 'מקצוע' in cell_str:
                    course_name_col = idx
                elif 'נקודות' in cell_str:
                    credit_points_col = idx
                elif 'ציון' in cell_str or 'זיכויים' in cell_str:
                    grade_col = idx
            
            # Course number might be in first or last column, or embedded in course name
            # We'll search for it in the parsing phase
            
            # Parse data rows
            for row_idx in range(header_row_idx + 1, len(table)):
                row = table[row_idx]
                if not row or len(row) < 2:
                    continue
                
                # Check if this row contains semester/year info
                row_text = ' '.join([str(cell) for cell in row if cell])
                semester_match = re.search(r'(תשפ["\']?ה|תשפ["\']?ד|תשפ["\']?ג|תשפ["\']?ב|תשפ["\']?א)\s+(חורף|קיץ|אביב)', row_text)
                if semester_match:
                    current_semester = semester_match.group(2)
                    year_match = re.search(r'(\d{4})\s*-\s*(\d{4})', row_text)
                    if year_match:
                        current_year = int(year_match.group(1))
                    continue
                
                # Extract course data from row
                course = self._parse_table_row(row, course_name_col, course_number_col, 
                                              credit_points_col, grade_col, 
                                              current_semester, current_year)
                
                if course and self._is_valid_course(course):
                    courses.append(course)
        
        # Post-process: identify retakes
        course_numbers = {}
        for course in courses:
            course_num = course.get('course_number')
            if course_num:
                if course_num not in course_numbers:
                    course_numbers[course_num] = []
                course_numbers[course_num].append(course)
        
        # Mark retakes
        for course_num, course_list in course_numbers.items():
            if len(course_list) > 1:
                for idx, course in enumerate(course_list):
                    if idx > 0:
                        course['retake_count'] = idx
                        if not course.get('notes'):
                            course['notes'] = 'מועד ב'
                        elif 'מועד ב' not in course.get('notes', ''):
                            course['notes'] = course.get('notes', '') + ', מועד ב'
        
        return courses
    
    def _parse_table_row(self, row: List, course_name_col: Optional[int], 
                        course_number_col: Optional[int], 
                        credit_points_col: Optional[int], 
                        grade_col: Optional[int],
                        semester: Optional[str], 
                        year: Optional[int]) -> Optional[Dict]:
        """
        Parse a single table row into a course dictionary
        """
        if not row or len(row) == 0:
            return None
        
        course = {
            'course_number': None,
            'course_name': None,
            'credit_points': None,
            'grade': None,
            'letter_grade': None,
            'semester': semester,
            'year': year,
            'notes': None,
            'is_passed': True,
            'retake_count': 0
        }
        
        # Extract course number
        if course_number_col is not None and course_number_col < len(row):
            cell = row[course_number_col]
            if cell:
                cell_str = str(cell).strip()
                # Look for course number (6-8 digits)
                course_num_match = re.search(r'(\d{6,8})', cell_str)
                if course_num_match:
                    course['course_number'] = course_num_match.group(1)
        
        # Extract course name
        if course_name_col is not None and course_name_col < len(row):
            cell = row[course_name_col]
            if cell:
                name = str(cell).strip()
                # Clean up name
                name = re.sub(r'^\d{6,8}\s*', '', name)  # Remove course number if present
                name = re.sub(r'\s+', ' ', name).strip()
                if name and len(name) > 2:
                    course['course_name'] = name
        
        # Extract credit points
        if credit_points_col is not None and credit_points_col < len(row):
            cell = row[credit_points_col]
            if cell:
                try:
                    credit_val = float(str(cell).strip())
                    if 0 <= credit_val <= 10:
                        course['credit_points'] = credit_val
                except (ValueError, AttributeError):
                    pass
        
        # Extract grade
        if grade_col is not None and grade_col < len(row):
            cell = row[grade_col]
            if cell:
                cell_str = str(cell).strip()
                
                # Check for numeric grade
                grade_match = re.search(r'(\d{2,3})', cell_str)
                if grade_match:
                    grade_val = int(grade_match.group(1))
                    if 0 <= grade_val <= 100:
                        course['grade'] = float(grade_val)
                
                # Check for status (פטור, עובר, etc.)
                status_patterns = {
                    'פטור': 'פטור',
                    'פטור ללא ניקוד': 'פטור ללא ניקוד',
                    'פטור עם ניקוד': 'פטור עם ניקוד',
                    'עובר': 'עובר',
                }
                
                notes_parts = []
                for pattern, status in status_patterns.items():
                    if pattern in cell_str:
                        notes_parts.append(status)
                        if 'פטור' in pattern and 'ללא ניקוד' in pattern:
                            course['credit_points'] = 0
                
                # Check for asterisk (מועד ב)
                if '*' in cell_str:
                    notes_parts.append('מועד ב')
                
                if notes_parts:
                    course['notes'] = ', '.join(notes_parts)
        
        # If course name column contains both name and number, extract both
        if course_name_col is not None and course_name_col < len(row):
            cell = row[course_name_col]
            if cell:
                cell_str = str(cell).strip()
                # Check if course number is embedded in the name cell
                course_num_in_name = re.search(r'(\d{6,8})', cell_str)
                if course_num_in_name and not course['course_number']:
                    course['course_number'] = course_num_in_name.group(1)
                    # Remove course number from name
                    cell_str = re.sub(r'\d{6,8}\s*', '', cell_str).strip()
                
                # If we don't have a name yet, use this cell
                if not course['course_name'] and cell_str:
                    # Clean up the name
                    cell_str = re.sub(r'^\d+\.?\d*\s*', '', cell_str)  # Remove leading numbers
                    cell_str = re.sub(r'\s+', ' ', cell_str).strip()
                    if len(cell_str) > 2:
                        course['course_name'] = cell_str
        
        # If we didn't find course name in expected column, try to find it in any cell
        if not course['course_name']:
            for cell in row:
                if not cell:
                    continue
                cell_str = str(cell).strip()
                # Check if this looks like a course name (Hebrew text, not just numbers)
                hebrew_chars = len(re.findall(r'[א-ת]', cell_str))
                if hebrew_chars >= 3 and not re.match(r'^[\d.\s]+$', cell_str):
                    # Check if it's not a course number
                    if not re.match(r'^\d{6,8}$', cell_str):
                        # Remove course number if embedded
                        cell_str = re.sub(r'\d{6,8}\s*', '', cell_str).strip()
                        if cell_str:
                            course['course_name'] = cell_str
                            break
        
        # If we didn't find course number in expected column, search all cells
        if not course['course_number']:
            for cell in row:
                if not cell:
                    continue
                cell_str = str(cell).strip()
                # Look for standalone course number (6-8 digits)
                if re.match(r'^\d{6,8}$', cell_str):
                    course['course_number'] = cell_str
                    break
                # Or embedded in text
                course_num_match = re.search(r'\b(\d{6,8})\b', cell_str)
                if course_num_match:
                    course['course_number'] = course_num_match.group(1)
                    break
        
        # Only return if we have at least course name or number
        if course['course_name'] or course['course_number']:
            return course
        
        return None
    
    def _extract_courses(self, text: str) -> List[Dict]:
        """
        Extract course information from text
        Handles different table formats across pages
        """
        courses = []
        lines = text.split('\n')
        
        # Patterns to exclude (lines that should not be parsed as courses)
        exclude_patterns = [
            r'נכון לתאריך',
            r'ת\.?ז\.?[:\s]*\d{9}',  # ID number lines
            r'^([א-ת\s]+)\s+ת\.?ז\.?',  # Name + ID lines
            r'פקולטה[:\s]*',
            r'לתואר[:\s]*',
            r'ממוצע מצטבר',
            r'שיעור הצלחות',
            r'נקודות מצטברות',
            r'גיליון ציונים',
            r'לימודי הסמכה',
            r'Undergraduate Studies',
            r'עמוד \d+ מתוך \d+',
            r'סוף גיליון',
            r'מזכירה אקדמית',
        ]
        
        # Find table sections (between headers and end markers)
        in_table = False
        current_semester = None
        current_year = None
        
        for i, line in enumerate(lines):
            line = line.strip()
            if not line:
                continue
            
            # Skip lines that match exclude patterns
            should_exclude = False
            for pattern in exclude_patterns:
                if re.search(pattern, line, re.IGNORECASE):
                    should_exclude = True
                    break
            if should_exclude:
                continue
            
            # Detect semester/year in line (e.g., "תשפ\"ה חורף 2024-2025")
            semester_match = re.search(r'(תשפ["\']?ה|תשפ["\']?ד|תשפ["\']?ג|תשפ["\']?ב|תשפ["\']?א)\s+(חורף|קיץ|אביב)', line)
            if semester_match:
                current_semester = semester_match.group(2)  # חורף/קיץ/אביב
                # Try to extract year
                year_match = re.search(r'(\d{4})\s*-\s*(\d{4})', line)
                if year_match:
                    current_year = int(year_match.group(1))
                continue  # Skip semester line itself
            
            # Look for course number pattern (6-8 digits)
            course_num_match = re.search(self.patterns['course_number'], line)
            if course_num_match:
                course = self._parse_course_line(line, current_semester, current_year)
                if course and self._is_valid_course(course):
                    courses.append(course)
        
        # Post-process: identify retakes (same course number appears multiple times)
        course_numbers = {}
        for course in courses:
            course_num = course.get('course_number')
            if course_num:
                if course_num not in course_numbers:
                    course_numbers[course_num] = []
                course_numbers[course_num].append(course)
        
        # Mark retakes
        for course_num, course_list in course_numbers.items():
            if len(course_list) > 1:
                # Sort by year/semester if available
                for idx, course in enumerate(course_list):
                    if idx > 0:  # First occurrence is original, others are retakes
                        course['retake_count'] = idx
                        # Add note about retake
                        if not course.get('notes'):
                            course['notes'] = 'מועד ב'
                        elif 'מועד ב' not in course.get('notes', ''):
                            course['notes'] = course.get('notes', '') + ', מועד ב'
        
        return courses
    
    def _is_valid_course(self, course: Dict) -> bool:
        """
        Validate that a course entry is actually a course and not parsed metadata
        """
        course_name = course.get('course_name', '')
        if course_name:
            course_name = course_name.strip()
        else:
            course_name = ''
        course_number = course.get('course_number', '')
        
        # Invalid course name patterns
        invalid_patterns = [
            r'^ת\.?ז\.?',
            r'נכון לתאריך',
            r'^[א-ת\s]{1,3}$',  # Too short (likely not a course name)
            r'פקולטה',
            r'לתואר',
            r'ממוצע',
            r'שיעור',
            r'נקודות מצטברות',
            r'גיליון',
            r'תעודת ציונים',
            r'תעודת.*ציונים',
            r'גליון.*ציונים',
            r'ציונים.*של',
            r'עמוד',
            r'סוף',
            r'^[:\.\s]+',  # Starts with punctuation only
            r'^[א-ת\s]*ת\.?ז\.?[א-ת\s]*$',  # Only contains ת.ז.
            r'גלמידי|מעין',  # Common OCR errors
        ]
        
        # Check course name
        for pattern in invalid_patterns:
            if re.search(pattern, course_name, re.IGNORECASE):
                return False
        
        # Course name should have at least 3 Hebrew characters (or valid course name)
        hebrew_chars = len(re.findall(r'[א-ת]', course_name))
        if hebrew_chars < 3 and not course_number:
            return False
        
        # If we have a course number, it's more likely to be valid
        if course_number:
            # Course numbers should be 6-8 digits
            if len(course_number) < 6 or len(course_number) > 8:
                return False
            # If course name is mostly numbers or very short, probably invalid
            if len(course_name) < 5 and not any(c.isalpha() for c in course_name):
                return False
        
        return True
    
    def _parse_course_line(self, line: str, semester: Optional[str], year: Optional[int]) -> Optional[Dict]:
        """
        Parse a single line containing course information
        Handles different formats:
        - Format 1: "00940345 מתמטיקה דיסקרטית ת' 4 70 פטור"
        - Format 2: "940219 הנדסת תוכנה 3.5 עובר"
        - Format 3: "72 4 מבני נתונים ואלגוריתמים"
        """
        course = {
            'course_number': None,
            'course_name': None,
            'credit_points': None,
            'grade': None,
            'letter_grade': None,
            'semester': semester,
            'year': year,
            'notes': None,
            'is_passed': True,
            'retake_count': 0
        }
        
        # Extract course number
        course_num_match = re.search(self.patterns['course_number'], line)
        if course_num_match:
            course['course_number'] = course_num_match.group(1)
            # Remove course number from line for further parsing
            line = line.replace(course_num_match.group(1), '', 1)
        
        # Extract numeric grade (can be at start or end)
        grade_match = re.search(r'\b(\d{2,3})\b', line)
        if grade_match:
            grade_val = int(grade_match.group(1))
            # Check if it's a valid grade (0-100)
            if 0 <= grade_val <= 100:
                course['grade'] = float(grade_val)
        
        # Extract credit points (usually decimal like 3.5, 4.0, etc.)
        credit_match = re.search(r'\b(\d+\.?\d*)\b', line)
        if credit_match:
            credit_val = float(credit_match.group(1))
            # Credit points are typically 0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5, 5.5, 6
            if 0 <= credit_val <= 10:
                course['credit_points'] = credit_val
        
        # Check for special statuses
        status_patterns = {
            'פטור': 'פטור',
            'פטור ללא ניקוד': 'פטור ללא ניקוד',
            'פטור עם ניקוד': 'פטור עם ניקוד',
            'עובר': 'עובר',
            '*עובר': 'עובר (מועד ב)',
            'מועד ב': 'מועד ב',
        }
        
        notes_parts = []
        for pattern, status in status_patterns.items():
            if pattern in line:
                notes_parts.append(status)
                # If it's פטור or עובר without grade, mark accordingly
                if 'פטור' in pattern or 'עובר' in pattern:
                    if course.get('grade') is None:
                        course['is_passed'] = True
                        # פטור usually means no grade, but passed
                        if 'פטור' in pattern:
                            if 'ללא ניקוד' in pattern:
                                course['credit_points'] = 0
                        elif 'עובר' in pattern:
                            # עובר means passed but no numeric grade
                            pass
        
        # Check for asterisk (*) indicating retake/מועד ב
        if '*' in line and 'מועד ב' not in ' '.join(notes_parts):
            notes_parts.append('מועד ב')
        
        if notes_parts:
            course['notes'] = ', '.join(notes_parts)
        
        # Extract course name (everything else that's not numbers/status)
        # Remove course number, grades, credits, statuses
        name_line = line
        # Remove course number
        if course['course_number']:
            name_line = re.sub(course['course_number'], '', name_line)
        # Remove numeric values (grades/credits)
        name_line = re.sub(r'\b\d+\.?\d*\b', '', name_line)
        # Remove status keywords
        for pattern in status_patterns.keys():
            name_line = name_line.replace(pattern, '')
        # Clean up
        name_line = re.sub(r'\s+', ' ', name_line).strip()
        
        # Filter out common non-course-name words
        words_to_remove = ['נקודות', 'ציון', 'מקצוע', 'זיכויים']
        for word in words_to_remove:
            name_line = name_line.replace(word, '')
        name_line = re.sub(r'\s+', ' ', name_line).strip()
        
        if name_line and len(name_line) > 2:  # Minimum course name length
            course['course_name'] = name_line
        
        # Only return course if we have at least course number or name
        if course['course_number'] or course['course_name']:
            return course
        
        return None
    
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
