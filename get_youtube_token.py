from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

flow = InstalledAppFlow.from_client_secrets_file(
    "client_secret.json",   # the file you downloaded
    scopes=SCOPES
)
creds = flow.run_local_server(port=0)

print("\n=== SAVE THESE ===")
print("Access Token :", creds.token)
print("Refresh Token:", creds.refresh_token)
print("Client ID    :", creds.client_id)
print("Client Secret:", creds.client_secret)