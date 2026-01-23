
import logging as Log
import string
import os
import random
from datetime import datetime


def generate_tenant_id(tenant_id=None):
    """Generate tenant"""  
    tenants = [1, 5, 8, 19, 20]
    tenant = random.choice(tenants)
    return tenant
    
def generate_name(name=None, name_length=None):
    """Generate first_name and last_name

    Args:
        name (_type_, optional): _description_. Defaults to None.
    """
    name_length = 8
    name_string = ''.join(random.choices(string.ascii_letters, k=name_length))
    return name_string
     
def generate_username(username_length=None):
    """Generate a random username for testing
    """
    username_length = 8
    random_str = ''.join(random.choices(string.ascii_lowercase + string.digits, k=username_length))
    return random_str

def generate_random_email(domain=None, email_prefix=None, email_lenth=None):
    
    if not domain:
        domain = 'instntmny.com'
    
    if not email_prefix:
        email_prefix = 'testuser'
        
    email_lenth = 8
    random_email_string = ''.join(random.choices(string.ascii_lowercase, k=email_lenth))
    
    email = email_prefix + '_' + random_email_string + '@' + domain
    
    return email
    
def generate_business_name(name_length=None):
    """Generate a random business name for testing
    """
    username_length = 10
    random_str = ''.join(random.choices(string.ascii_letters, k=username_length))
    return random_str

def generate_contact_number(contact_number=None, number_length=None):
    """Generate a contact number for testing

    Args:
        contact_number (_type_, optional): _description_. Defaults to None.
    """
    number_length = 10
    
    number_string = ''.join(random.choices(string.digits, k=number_length))
    return number_string

def generate_random_location():
    """Generates random country, city, and state for testing purposes."""
    
    countries = [
        "USA", "Canada", "Germany", "Australia", "United Kingdom", "India", "France", "Brazil", "Mexico", "Japan"
    ]
    
    cities = {
        "USA": ["New York", "Los Angeles", "Chicago", "Houston", "Phoenix"],
        "Canada": ["Toronto", "Vancouver", "Montreal", "Calgary", "Ottawa"],
        "Germany": ["Berlin", "Munich", "Hamburg", "Frankfurt", "Cologne"],
        "Australia": ["Sydney", "Melbourne", "Brisbane", "Perth", "Adelaide"],
        "United Kingdom": ["London", "Manchester", "Birmingham", "Liverpool", "Edinburgh"],
        "India": ["New Delhi", "Mumbai", "Bangalore", "Chennai", "Kolkata"],
        "France": ["Paris", "Marseille", "Lyon", "Toulouse", "Nice"],
        "Brazil": ["São Paulo", "Rio de Janeiro", "Salvador", "Fortaleza", "Belo Horizonte"],
        "Mexico": ["Mexico City", "Guadalajara", "Monterrey", "Cancun", "Puebla"],
        "Japan": ["Tokyo", "Osaka", "Kyoto", "Sapporo", "Fukuoka"]
    }
    
    states = {
        "USA": ["California", "Texas", "Florida", "New York", "Illinois"],
        "Canada": ["Ontario", "Quebec", "British Columbia", "Alberta", "Manitoba"],
        "Germany": ["Bavaria", "Berlin", "North Rhine-Westphalia", "Hesse", "Saxony"],
        "Australia": ["New South Wales", "Victoria", "Queensland", "Western Australia", "South Australia"],
        "United Kingdom": ["England", "Scotland", "Wales", "Northern Ireland"],
        "India": ["Delhi", "Maharashtra", "Karnataka", "Tamil Nadu", "Uttar Pradesh"],
        "France": ["Île-de-France", "Provence-Alpes-Côte d'Azur", "Rhône-Alpes", "Languedoc-Roussillon", "Aquitaine"],
        "Brazil": ["São Paulo", "Rio de Janeiro", "Minas Gerais", "Bahia", "Paraná"],
        "Mexico": ["Jalisco", "Nuevo León", "Yucatán", "Chihuahua", "Guanajuato"],
        "Japan": ["Tokyo", "Osaka", "Hokkaido", "Kyoto", "Okinawa"]
    }
    
    # Randomly choose a country
    _country = random.choice(countries)
    
    # Randomly choose a city and state based on the country
    _city = random.choice(cities.get(_country, []))
    _state = random.choice(states.get(_country, []))
    
    return _country, _city, _state

def generate_random_postcode(country=None):
    """Generates a random postcode based on the country."""
    
    if not country:
        country = "United Kingdom"
    
    # Define some example postcode formats for different countries
    postcode_formats = {
        "USA": "#####",  # 5 digits
        "Canada": "A1A 1A1",  # Alphanumeric format: A=letter, 1=digit
        "United Kingdom": "A1 1AA",  # Alphanumeric format: A=letter, 1=digit
        "Australia": "####",  # 4 digits
        "Germany": "#####",  # 5 digits
        "India": "######",  # 6 digits
        "France": "#####",  # 5 digits
        "Japan": "###-####",  # 3 digits-4 digits
    }
    
    if country not in postcode_formats:
        raise ValueError(f"No postcode format available for {country}")
    
    # Get the postcode format for the given country
    format_string = postcode_formats[country]
    
    postcode = ""
    for char in format_string:
        if char == "A":
            # Generate a random letter
            postcode += random.choice(string.ascii_uppercase)
        elif char == "1":
            # Generate a random digit
            postcode += random.choice(string.digits)
        else:
            # Add the character directly (space or dash)
            postcode += char
    
    return postcode

def generate_random_currency():
    """Generates a random currency code."""
    
    # List of common currency codes
    currencies = [
        "USD",  # US Dollar
        "EUR",  # Euro
        "GBP",  # British Pound
        "INR",  # Indian Rupee
        "JPY",  # Japanese Yen
        "AUD",  # Australian Dollar
        "CAD",  # Canadian Dollar
        "CHF",  # Swiss Franc
        "CNY",  # Chinese Yuan
        "NZD",  # New Zealand Dollar
        "SGD",  # Singapore Dollar
        "HKD",  # Hong Kong Dollar
        "MXN",  # Mexican Peso
        "BRL",  # Brazilian Real
        "ZAR",  # South African Rand
        "SEK",  # Swedish Krona
        "NOK",  # Norwegian Krone
        "DKK",  # Danish Krone
        "RUB",  # Russian Ruble
        "KRW",  # South Korean Won
        "TRY",  # Turkish Lira
    ]
    
    # Randomly choose a currency code from the list
    currency = random.choice(currencies)
    
    return currency

def generate_random_timezone():
    """Generates a random time zone."""
    
    # List of common time zones
    time_zones = [
        "UTC",  # Coordinated Universal Time
        "PST",  # Pacific Standard Time (US)
        "EST",  # Eastern Standard Time (US)
        "CST",  # Central Standard Time (US)
        "MST",  # Mountain Standard Time (US)
        "GMT",  # Greenwich Mean Time
        "BST",  # British Summer Time
        "CET",  # Central European Time
        "EET",  # Eastern European Time
        "IST",  # Indian Standard Time
        "JST",  # Japan Standard Time
        "AEST", # Australian Eastern Standard Time
        "NZST", # New Zealand Standard Time
        "SGT",  # Singapore Time
        "UTC+1",  # UTC + 1 Hour
        "UTC-5",  # UTC - 5 Hours
        "UTC+10",  # UTC + 10 Hours
        "ACDT",  # Australian Central Daylight Time
        "WAT",  # West Africa Time
        "PDT",  # Pacific Daylight Time (US)
        "EDT",  # Eastern Daylight Time (US)
    ]
    
    # Randomly choose a timezone from the list
    timezone = random.choice(time_zones)
    
    return timezone

def get_current_date():
    # Get the current date and format it as YYYY-MM-DD
    return datetime.now().strftime("%Y-%m-%d")

