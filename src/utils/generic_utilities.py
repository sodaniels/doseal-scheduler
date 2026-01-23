
import logging as Log
import string
import os
import random
from datetime import datetime
from app.utils.redis import (
    get_redis, get_redis
)


def generate_tenant_id(tenant_id=None):
    """Generate tenant"""  
    tenants = [1, 5, 8, 19, 20]
    tenant = random.choice(tenants)
    return 1

def generate_device_id():
    prefix = "30563869"
    # Generate either 2 or 3 digits randomly
    num_digits = random.choice([2, 3])
    suffix = ''.join(str(random.randint(0, 9)) for _ in range(num_digits))
    return prefix + suffix

def generate_country_iso_2(country_iso_2=None):
    """Generate country_iso_2"""  
    return "GB"

def generate_country_iso_3(country_iso_3=None):
    """Generate country_iso_3"""  
    return "USA"

def generate_origion_currentcy(origion_currentcy=None):
    """Generate origion_currentcy"""  
    return "USD"
    
def generate_first_name():
    """Generate first_name and last_name

    Args:
        name (_type_, optional): _description_. Defaults to None.
    """
    first_names = [
        "Juan", "María", "José", "Guadalupe", "Luis", "Ana", "Miguel",
        "Carmen", "Francisco", "Jesús", "Alejandro", "Patricia",
        "Carlos", "Lucía", "Sofía", "Antonio", "Fernanda", "Jorge",
        "Roberto", "Paola"
    ]
    
    return random.choice(first_names)

def generate_lastname_name():
    """Generate first_name and last_name

    Args:
        name (_type_, optional): _description_. Defaults to None.
    """
    last_names = [
        "Hernández", "García", "Martínez", "López", "González",
        "Pérez", "Rodríguez", "Sánchez", "Ramírez", "Cruz",
        "Flores", "Gómez", "Morales", "Vázquez", "Jiménez",
        "Reyes", "Torres", "Ruiz", "Castillo", "Ortiz"
    ]
    
    return random.choice(last_names)

def generate_lastname_name2():
    """Generate first_name and last_name

    Args:
        name (_type_, optional): _description_. Defaults to None.
    """
    last_names = [
        "Hernández", "García", "Martínez", "López", "González",
        "Pérez", "Rodríguez", "Sánchez", "Ramírez", "Cruz",
        "Flores", "Gómez", "Morales", "Vázquez", "Jiménez",
        "Reyes", "Torres", "Ruiz", "Castillo", "Ortiz"
    ]
    
    return random.choice(last_names)
   
    
def generate_name(name=None, name_length=None):
    """Generate first_name and last_name

    Args:
        name (_type_, optional): _description_. Defaults to None.
    """
    name_length = 8
    name_string = ''.join(random.choices(string.ascii_letters, k=name_length))
    return name_string
     
def generate_username():
    """Generate a random UK mobile phone number with fixed prefix and random last 4 digits."""
    
    # Fixed part of the phone number
    fixed_prefix = "4475689838"  # This part is constant
    
    # Randomly generate the last 4 digits
    random_digits = ''.join(random.choices('0123456789', k=2))
    
    # Construct the full phone number
    uk_phone_number = f"{fixed_prefix}{random_digits}"
    
    return uk_phone_number

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

def generate_delivery_data():
    deliver_date = {
        "style_id": 3,
        "transaction_type_id": 1,
        "delivery_type": "W",
        "sender_payment_method_id": 3,
    }
    return deliver_date

def generate_address():
    """
    Generate a random Mexico-style address.
    Returns:
        str: A random address string
    """
    street_types = ["Calle", "Avenida", "Boulevard", "Privada", "Andador"]
    street_names = [
        "Juárez", "Hidalgo", "Reforma", "Independencia", "Morelos",
        "Zaragoza", "Insurgentes", "Madero", "Allende", "Niños Héroes"
    ]
    neighborhoods = [
        "Centro", "Roma Norte", "Polanco", "Condesa", "Del Valle", 
        "Coyoacán", "Santa Fe", "Lomas", "Napoles", "Tacuba"
    ]
    cities = [
        "Ciudad de México", "Guadalajara", "Monterrey", "Puebla", "Tijuana",
        "Cancún", "Mérida", "León", "Querétaro", "Toluca"
    ]
    postal_codes = [
        "06000", "44100", "64000", "72000", "22000",
        "77500", "97000", "37000", "76000", "50000"
    ]
    state = random.choice([
        "CDMX", "Jalisco", "Nuevo León", "Puebla", "Baja California",
        "Quintana Roo", "Yucatán", "Guanajuato", "Querétaro", "México"
    ])

    number = random.randint(1, 9999)
    street_type = random.choice(street_types)
    street = random.choice(street_names)
    neighborhood = random.choice(neighborhoods)
    city = random.choice(cities)
    postal_code = random.choice(postal_codes)

    address = f"{street_type} {street} {number}, Col. {neighborhood}, {postal_code} {city}, {state}, México"
    return address

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

def get_otp(username):
    redisKey = f'otp_token_{username}'
    otp_raw = get_redis(redisKey)
    otp = otp_raw.decode("utf-8")
    if otp:
        return otp
    return None

def generate_id_number(id_length=8):
    """
    Generate a random ID number consisting of digits.
    
    Args:
        id_length (int): Length of the ID number (default is 8)
        
    Returns:
        str: A random ID number string
    """
    return ''.join(random.choices(string.digits, k=id_length))

def generate_amount(min_amount=1.0, max_amount=100.0, decimals=2):
    """
    Generate a random amount as a float, rounded to given decimals.

    Args:
        min_amount (float): Minimum amount (default 1.0)
        max_amount (float): Maximum amount (default 100.0)
        decimals (int): Number of decimal places (default 2)

    Returns:
        float: A random amount
    """
    amount = random.uniform(min_amount, max_amount)
    return round(amount, decimals)

def generate_mexico_phone_number():
    """
    Generate a random Mexican mobile phone number.
    Returns:
        str: A phone number string in the format +52 1 XXX XXX XXXX
    """
    # The mobile prefix after +52 is typically '1'
    prefix = "521"
    # Generate a 10-digit number (Mexican numbers: 3-digit area code + 7-digit number)
    area_code = random.randint(200, 999)  # Avoids non-geographic codes
    number_part = random.randint(1000000, 9999999)
    # Format: +52 1 XXX XXX XXXX
    return f"{prefix}{area_code}{str(number_part)[:3]}"

def generate_otp(id_length=6):
    """
    Generate a random OTP.
    
    Args:
        id_length (int): Length of the ID number (default is 6)
        
    Returns:
        str: A random ID number string
    """
    return ''.join(random.choices(string.digits, k=id_length))

def generate_id_type(id_type="Passport"):
    """
    Generate a random ID number based on the ID type.
    
    Supported types: Passport, Driving Licence, National Identity Card
    """
    
    type_collection = ["Passport", "Driving Licence", "National Identity Card"]
    
    id_type = random.choices(type_collection)
    
    return id_type
    
   
def generate_image_url(width=400, height=300):
    """
    Generate a random image URL using picsum.photos.

    Args:
        width (int): Width of the image
        height (int): Height of the image

    Returns:
        str: A random image URL
    """
    random_id = random.randint(1, 1000)
    return f"https://picsum.photos/id/{random_id}/{width}/{height}"

def generate_latitude():
    """Generate a latitude between 32.77 and 41.21 (e.g., within the continental US)."""
    return "25.7617"

def generate_longitude():
    """Generate a longitude between -117.15 and -79.56 (negative for western hemisphere)."""
    return "-80.1918"

def generate_us_phone_number():
    prefix = "13018867"
    # Generate a three-digit random number (100–999)
    suffix = str(random.randint(100, 999))
    return prefix + suffix

def generate_login_payload(password=None, email=None):
    """
    Helper function to create login payload with all required fields.
    The function ensures that the required fields are provided.
    """
    
    auto_email = get_redis('automated_test_email')
    auto_password= get_redis('automated_test_password')
        
    env_email = auto_email.decode("utf-8")
    env_password = auto_password.decode("utf-8")
    
    # Create and return the password data dictionary
    password_data = {
        "email": env_email,
        "password": env_password,
    }
    return password_data

def generate_business_payload(tenant_id=None,  business_name=None, start_date=None, business_contact=None, 
                        country=None, city=None, state=None, postcode=None, currency=None, alternate_contact_number=None, 
                        time_zone=None, first_name=None, last_name=None, username=None, password=None, email=None, 
                        store_url=None, package=None, otp=None, return_url=None, website=None, us_phone_number=None, latitude=None,
                        device_id=None, longitude=None, country_iso_3=None, origin_currency=None,
                        amount=None, delivery_data=None,address=None, mexico_number=None, last_name2=None, **kwargs):
    """
    Helper function to create business payload with all required fields.
    The function ensures that the required fields are provided.
    """
    
    # Assign default values or generate random ones for optional fields
    tenant_id = tenant_id or generate_tenant_id()
    business_name = business_name or generate_business_name()
    start_date = start_date or get_current_date()
    business_contact = business_contact or generate_contact_number()
    username = username or generate_username()
    password = password or 'Password123' # Default password
    email = email or generate_random_email()
    _country, _city, _state = generate_random_location()
    country = country or _country
    city = city or _city
    state = state or _state
    website = website or "http://localhost:9090"
    postcode = postcode or generate_random_postcode()
    currency = currency or generate_random_currency()
    alternate_contact_number = alternate_contact_number or generate_contact_number()
    time_zone = time_zone or generate_random_timezone()
    first_name = first_name or generate_first_name()
    last_name = last_name or generate_lastname_name()
    last_name2 = last_name2 or generate_lastname_name2()
    store_url = store_url or f"{business_name.lower().replace(' ', '')}com"
    package = package or 'Basic'
    return_url = return_url or 'http://localhost:9090/return'
    id_type = generate_id_type()
    id_number = generate_id_number()
    image_url = generate_image_url()
    otp = otp or generate_otp()
    country_iso_2 = generate_country_iso_2()
    us_phone_number = us_phone_number or generate_us_phone_number()
    device_id = device_id or generate_device_id()
    latitude = latitude or generate_latitude()
    longitude = longitude or generate_longitude()
    country_iso_3 = country_iso_3 or generate_country_iso_3()
    origin_currency = origin_currency or generate_origion_currentcy()
    amount = amount or generate_amount()
    delivery_data = delivery_data or generate_delivery_data()
    address = address or generate_address()
    mexico_number = mexico_number or generate_mexico_phone_number()
    
    # Create and return the business data dictionary
    business_data = {
        "tenant_id": tenant_id,
        "business_name": business_name,
        "start_date": start_date,
        "business_contact": business_contact,
        "country": country,
        "city": city,
        "state": state,
        "postcode": postcode,
        "currency": currency,
        "website": website,
        "alternate_contact_number": alternate_contact_number,
        "time_zone": time_zone,
        "first_name": first_name,
        "last_name": last_name,
        "last_name2": last_name2,
        "username": username,
        "password": password,
        "email": email,
        "store_url": store_url,
        "package": package,
        "return_url": return_url,
        "id_type": id_type,
        "id_number": id_number,
        "image_url": image_url,
        "country_iso_2": country_iso_2,
        "us_phone_number": us_phone_number,
        "device_id": device_id,
        "otp": otp,
        "latitude": latitude,
        "longitude": longitude,
        "country_iso_3": country_iso_3,
        "origin_currency": origin_currency,
        "amount": amount,
        "delivery_data": delivery_data,
        "address": address,
        "mexico_number": mexico_number,
    }
    
    # Include any additional fields passed as kwargs
    business_data.update(kwargs)
    
    return business_data





