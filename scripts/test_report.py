import datetime
import requests

# URL = "ml.notawebsite.net"
URL = "localhost"

# current date without milliseconds
date = datetime.datetime.now().strftime("%Y-%m-%d")

response = requests.get(f"http://{URL}:5000/api/generate-report?date={date}")
print(response.status_code)
print(response.json())
