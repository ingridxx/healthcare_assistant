import singlestoredb as s2
from dotenv import load_dotenv
import os

load_dotenv()

# Create a dictionary with the required parameters
connection_params = {
    "host": os.getenv("SINGLESTORE_HOST"),
    "port": 3306,
    "user": os.getenv("SINGLESTORE_USER"),
    "password": os.getenv("SINGLESTORE_PASSWORD"),
    "database": os.getenv("SINGLESTORE_DB"),
}
s2_conn = s2.connect(**connection_params)

s2_cur = s2_conn.cursor()
s2_cur.execute("""
SELECT heart_rate, blood_pressure, glucose_level, activity_level FROM vitals ORDER BY timestamp DESC LIMIT 1;
""")
results = s2_cur.fetchall()

# Convert results to a list of dictionaries
columns = [col[0] for col in s2_cur.description]
metrics = [dict(zip(columns, row)) for row in results]

print(metrics)