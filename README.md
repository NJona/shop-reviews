# shop-reviews

Demo app for Codesphere global deployments. Its landscape (`ci.prod.yml`) has one private `reviews` service. Added
to the `shop` global config, the storefront's `api-gateway` calls it through `REVIEWS_URL`, which the global
deployment sets, not this repo.
