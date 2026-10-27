# shop-reviews

Demo app for Codesphere global deployments. Its landscape (`ci.prod.yml`) has one private `reviews` service that keeps
ratings in Postgres. The database is not part of the landscape: the global config declares it as a standalone managed
service of the app, so a migration can back it up and restore it in another data center. The app gets its address and
password as `REVIEWS_DB_*` env vars; the storefront's `api-gateway` reaches the app through `REVIEWS_URL`. Both are set
by the global deployment, not by this repo.
