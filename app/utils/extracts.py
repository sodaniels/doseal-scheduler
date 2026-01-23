import pandas as pd
from bson.objectid import ObjectId
from marshmallow import ValidationError
from io import BytesIO

import pandas as pd
from io import BytesIO
from marshmallow import ValidationError
import re

import pandas as pd
from io import BytesIO
from marshmallow import ValidationError
import re

import pandas as pd
from io import BytesIO
from marshmallow import ValidationError
import re

def extract_contacts_from_excel(file):
    """
    Extract contacts from an Excel file and return them as a list.
    Assumes the Excel file has a 'contact' column.
    Removes characters typically used to format phone numbers (e.g., spaces, parentheses, dashes, plus signs).
    """
    try:
        # Read the Excel file into a pandas DataFrame
        df = pd.read_excel(BytesIO(file.read()))

        # Check if the 'contact' column exists in the Excel file
        if 'contact' not in df.columns:
            raise ValidationError("Excel file must contain a 'contact' column.")

        # Extract only the 'contact' column and convert it to a list
        contacts = df['contact'].dropna().tolist()  # dropna to remove any empty values

        if not contacts:
            raise ValidationError("No valid contacts found in the file.")

        # Convert contacts to strings and remove spaces, parentheses, dashes, plus signs, etc.
        sanitized_contacts = [
            re.sub(r"[^\d]", "", str(contact)) for contact in contacts
        ]

        return sanitized_contacts
    except Exception as e:
        # Log the full error message for debugging
        raise ValidationError(f"Error extracting contacts from Excel: {str(e)}")





