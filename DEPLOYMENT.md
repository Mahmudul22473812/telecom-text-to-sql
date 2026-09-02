# Deployment guide

The lowest-change public deployment keeps the Streamlit interface and uses:

- **Neon** for hosted PostgreSQL;
- **Gemini Developer API** for hosted chat and schema embeddings;
- **Streamlit Community Cloud** for the application;
- an **iframe** to show the application inside a Vercel portfolio.

Local development continues to use Ollama by default. Secrets must never be
committed to GitHub.

## 1. Verify the project locally

Install dependencies and local models:

```powershell
py -3 -m pip install -r requirements.txt
ollama pull llama3.2
ollama pull nomic-embed-text
```

Copy `.env.example` to `.env`, keep `AI_PROVIDER=ollama`, and enter the local
PostgreSQL settings. Then run:

```powershell
py -3 -m unittest discover -s tests -v
py -3 -m streamlit run streamlit_app.py --server.address localhost
```

## 2. Create the hosted PostgreSQL database

1. Create a Neon project at <https://console.neon.tech/>.
2. Choose a region close to the Streamlit deployment and copy the **direct**
   owner connection string.
3. Add it only to your local `.env`:

   ```dotenv
   DATABASE_ADMIN_URL=postgresql://owner:password@direct-host/dbname?sslmode=require
   ```

4. Import the five Excel workbooks. The importer creates missing tables and
   indexes before loading the data:

   ```powershell
   py -3 scripts\import_data.py
   ```

The importer replaces the contents of the five telecom tables. Use the owner
URL only for this setup operation. Do not give the owner URL to the public app.

## 3. Create the public application's read-only database role

Choose a strong password and add these local values to `.env`:

```dotenv
APP_DB_USER=telecom_reader
APP_DB_PASSWORD=replace_with_a_different_strong_password
```

Run:

```powershell
py -3 scripts\create_readonly_role.py
```

In Neon's **Connect** dialog, select `telecom_reader`, enable connection
pooling, and copy its pooled URL. The hostname should contain `-pooler`. This
pooled URL becomes the public application's `DATABASE_URL`.

Keep `DATABASE_ADMIN_URL` local. The Streamlit application receives only the
read-only role URL.

## 4. Create the hosted AI key

1. Open <https://aistudio.google.com/apikey> and create a Gemini API key.
2. Keep the key private. It belongs only in local `.env` or Streamlit's Secrets
   settings.
3. For a cloud test, temporarily configure `.env` as follows:

   ```dotenv
   AI_PROVIDER=gemini
   GEMINI_API_KEY=replace_with_your_key
   GEMINI_CHAT_MODEL=gemini-3.6-flash
   GEMINI_EMBEDDING_MODEL=gemini-embedding-001
   DATABASE_URL=postgresql://telecom_reader:password@host-pooler/dbname?sslmode=require
   ```

4. Start Streamlit locally and test clear, ambiguous, ranking, and unsupported
   questions before publishing.

The Google free tier is suitable for a small demonstration but has lower rate
limits, and its data-use terms differ from paid service. Review those terms
before sending private or production data.

## 5. Deploy the application on Streamlit Community Cloud

1. Push the deployment changes to GitHub.
2. Open <https://share.streamlit.io/> and choose **Create app**.
3. Select the repository, branch `main`, and entrypoint `streamlit_app.py`.
4. Open **Advanced settings** and select a supported Python version.
5. Paste the following into **Secrets**, replacing both secret values:

   ```toml
   AI_PROVIDER = "gemini"
   GEMINI_API_KEY = "your-real-key"
   GEMINI_CHAT_MODEL = "gemini-3.6-flash"
   GEMINI_EMBEDDING_MODEL = "gemini-embedding-001"

   DATABASE_URL = "postgresql://telecom_reader:password@host-pooler/dbname?sslmode=require"
   DB_CONNECT_TIMEOUT = "10"
   DB_STATEMENT_TIMEOUT_MS = "15000"
   ```

The same non-secret template is available in
`.streamlit/secrets.toml.example`. Never commit a real
`.streamlit/secrets.toml`; it is ignored by Git.

6. Deploy and test the public URL. If deployment fails, open **Manage app** and
   inspect its logs.

## 6. Embed it in a Vercel portfolio

For a normal HTML page:

```html
<iframe
  src="https://your-app-name.streamlit.app/?embed=true"
  title="Telecom Text-to-SQL Assistant"
  style="width: 100%; height: 900px; border: 0;"
  loading="lazy"
></iframe>
```

For a React or Next.js component:

```jsx
export default function TelecomDemo() {
  return (
    <iframe
      src="https://your-app-name.streamlit.app/?embed=true"
      title="Telecom Text-to-SQL Assistant"
      className="h-[900px] w-full border-0"
      loading="lazy"
    />
  );
}
```

Replace the URL with the real public Streamlit subdomain and deploy the
portfolio normally on Vercel.

## 7. Release checks

Run deterministic tests:

```powershell
py -3 -m unittest discover -s tests -v
```

Run the database-backed deployment gate against the hosted configuration:

```powershell
py -3 evaluation\evaluate_end_to_end.py --runs 3
```

The end-to-end gate measures intent classification, clarification, SQL
validation, database result equivalence, unsafe rejection, stability, and
latency. Changing from Llama to Gemini changes model behavior, so passing local
Ollama tests does not prove that every cloud-model case will pass. Run the
three-pass gate again with `AI_PROVIDER=gemini` before describing the hosted
version as fully verified.

## Production boundary

This setup is appropriate for a public portfolio demonstration. A larger
production service should additionally use account-level authentication,
central rate limiting, usage budgets, structured logs, monitoring, pagination,
and automated backups. The application already limits database statements to
15 seconds by default, rejects unsupported requests before model access,
validates SQL twice, uses read-only transactions, and supports a database role
that has only `SELECT` privileges.
