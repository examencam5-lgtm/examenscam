import requests

url = "https://sujetexa.com/robots.txt"
try:
    response = requests.get(url, timeout=10)
    if response.status_code == 200:
        print("Contenu de robots.txt :")
        print(response.text)
    else:
        print(f"robots.txt non trouvé (statut {response.status_code})")
except Exception as e:
    print(f"Erreur : {e}")