// ============================================================
// Anomaly Detection Demo — Service Dependency Graph
// 36 nodes, ~120 edges across 6 layers
// ============================================================

// Clear existing data
MATCH (n) DETACH DELETE n;

// ============================================================
// Layer 1: Edge (3 nodes)
// ============================================================
CREATE (cdn:Service:Edge {
  name: 'CDN',
  id: 'cdn',
  layer: 'edge',
  description: 'Content delivery and static asset caching'
})
CREATE (apigw:Service:Edge {
  name: 'API Gateway',
  id: 'apigw',
  layer: 'edge',
  description: 'Request routing, auth check, rate limit enforcement'
})
CREATE (lb:Service:Edge {
  name: 'Load Balancer',
  id: 'lb',
  layer: 'edge',
  description: 'Layer 7 load balancing across availability zones'
})

// ============================================================
// Layer 2: Domain Services (10 nodes)
// ============================================================
CREATE (order:Service:Domain {
  name: 'Order Service',
  id: 'order',
  layer: 'domain',
  team: 'orders',
  description: 'Order creation, status tracking, fulfillment orchestration'
})
CREATE (payment:Service:Domain {
  name: 'Payment Service',
  id: 'payment',
  layer: 'domain',
  team: 'payments',
  description: 'Payment processing, refunds, transaction recording'
})
CREATE (cart:Service:Domain {
  name: 'Cart Service',
  id: 'cart',
  layer: 'domain',
  team: 'commerce',
  description: 'Shopping cart state, session persistence'
})
CREATE (inventory:Service:Domain {
  name: 'Inventory Service',
  id: 'inventory',
  layer: 'domain',
  team: 'supply_chain',
  description: 'Stock levels, reservation, replenishment triggers'
})
CREATE (shipping:Service:Domain {
  name: 'Shipping Service',
  id: 'shipping',
  layer: 'domain',
  team: 'logistics',
  description: 'Shipping label generation, carrier integration, tracking'
})
CREATE (user:Service:Domain {
  name: 'User/Account Service',
  id: 'user',
  layer: 'domain',
  team: 'platform',
  description: 'User profiles, account management, preferences'
})
CREATE (search:Service:Domain {
  name: 'Search Service',
  id: 'search',
  layer: 'domain',
  team: 'discovery',
  description: 'Product search, filtering, faceted navigation'
})
CREATE (notify:Service:Domain {
  name: 'Notification Service',
  id: 'notify',
  layer: 'domain',
  team: 'engagement',
  description: 'Email, SMS, push notification dispatch'
})
CREATE (pricing:Service:Domain {
  name: 'Pricing Service',
  id: 'pricing',
  layer: 'domain',
  team: 'commerce',
  description: 'Dynamic pricing, discount rules, tax calculation'
})
CREATE (recommend:Service:Domain {
  name: 'Recommendation Service',
  id: 'recommend',
  layer: 'domain',
  team: 'discovery',
  description: 'ML-based product recommendations, personalization'
})

// ============================================================
// Layer 3: Platform Services (6 nodes)
// ============================================================
CREATE (auth:Service:Platform {
  name: 'Auth / IAM Service',
  id: 'auth',
  layer: 'platform',
  description: 'Authentication, JWT validation, RBAC'
})
CREATE (config:Service:Platform {
  name: 'Config Service',
  id: 'config',
  layer: 'platform',
  description: 'Centralized configuration, secret distribution'
})
CREATE (ratelimit:Service:Platform {
  name: 'Rate Limiter',
  id: 'ratelimit',
  layer: 'platform',
  description: 'Per-tenant and per-endpoint rate limiting'
})
CREATE (audit:Service:Platform {
  name: 'Audit Logger',
  id: 'audit',
  layer: 'platform',
  description: 'Compliance audit trail for sensitive operations'
})
CREATE (flagsvc:Service:Platform {
  name: 'Feature Flag Service',
  id: 'flagsvc',
  layer: 'platform',
  description: 'Feature toggles, progressive rollout control'
})
CREATE (mlmodel:Service:Platform {
  name: 'ML Model Service',
  id: 'mlmodel',
  layer: 'platform',
  description: 'Model serving endpoint for recommendations'
})

// ============================================================
// Layer 4: Middleware (7 nodes)
// ============================================================
CREATE (redis1:Service:Middleware {
  name: 'Redis Cluster 1',
  id: 'redis1',
  layer: 'middleware',
  purpose: 'sessions',
  description: 'Session store and auth token cache'
})
CREATE (redis2:Service:Middleware {
  name: 'Redis Cluster 2',
  id: 'redis2',
  layer: 'middleware',
  purpose: 'cache',
  description: 'Application cache, rate limit counters, feature cache'
})
CREATE (kafka:Service:Middleware {
  name: 'Kafka',
  id: 'kafka',
  layer: 'middleware',
  description: 'Event streaming for async workflows'
})
CREATE (rabbit:Service:Middleware {
  name: 'RabbitMQ',
  id: 'rabbit',
  layer: 'middleware',
  description: 'Task queue for notification dispatch'
})
CREATE (elastic:Service:Middleware {
  name: 'Elasticsearch',
  id: 'elastic',
  layer: 'middleware',
  description: 'Full-text search index and log aggregation'
})
CREATE (pgpri:Service:Middleware {
  name: 'PostgreSQL Primary',
  id: 'pgpri',
  layer: 'middleware',
  description: 'Primary relational database for transactional writes'
})
CREATE (pgrep:Service:Middleware {
  name: 'PG Read Replica',
  id: 'pgrep',
  layer: 'middleware',
  description: 'Read replica for reporting and non-critical reads'
})

// ============================================================
// Layer 5: Storage and Infrastructure (5 nodes)
// ============================================================
CREATE (mongo:Service:Storage {
  name: 'MongoDB',
  id: 'mongo',
  layer: 'storage',
  description: 'Document store for notification templates and logs'
})
CREATE (s3:Service:Storage {
  name: 'S3 Object Store',
  id: 's3',
  layer: 'storage',
  description: 'Config files, ML model artifacts, backups'
})
CREATE (vault:Service:Infra {
  name: 'Vault',
  id: 'vault',
  layer: 'infra',
  description: 'Secret management, credential rotation, encryption keys'
})
CREATE (dns:Service:Infra {
  name: 'DNS',
  id: 'dns',
  layer: 'infra',
  description: 'Domain name resolution for internal and external calls'
})
CREATE (mesh:Service:Infra {
  name: 'Service Mesh',
  id: 'mesh',
  layer: 'infra',
  description: 'mTLS, service discovery, internal traffic routing'
})

// ============================================================
// Layer 6: External Dependencies (5 nodes)
// ============================================================
CREATE (stripe:Service:External {
  name: 'Stripe',
  id: 'stripe',
  layer: 'external',
  description: 'Payment gateway — card processing, refunds'
})
CREATE (carrier:Service:External {
  name: 'Carrier API',
  id: 'carrier',
  layer: 'external',
  description: 'Shipping carrier rate quotes and label generation'
})
CREATE (sendgrid:Service:External {
  name: 'SendGrid',
  id: 'sendgrid',
  layer: 'external',
  description: 'Transactional email delivery'
})
CREATE (sms:Service:External {
  name: 'SMS Provider',
  id: 'sms',
  layer: 'external',
  description: 'SMS notification delivery'
})
CREATE (taxapi:Service:External {
  name: 'Tax API',
  id: 'taxapi',
  layer: 'external',
  description: 'Tax rate calculation by jurisdiction'
})

// ============================================================
// Relationships: DEPENDS_ON
// type: sync | async | cache | config
// criticality: critical | degraded | optional
// ============================================================

// --- Edge layer wiring ---
CREATE (cdn)-[:DEPENDS_ON {type: 'sync', criticality: 'critical'}]->(dns)
CREATE (lb)-[:DEPENDS_ON {type: 'sync', criticality: 'critical'}]->(dns)
CREATE (apigw)-[:DEPENDS_ON {type: 'sync', criticality: 'critical'}]->(lb)
CREATE (apigw)-[:DEPENDS_ON {type: 'sync', criticality: 'critical'}]->(cdn)

// --- API Gateway fans out to domain services ---
CREATE (apigw)-[:ROUTES_TO {type: 'sync'}]->(order)
CREATE (apigw)-[:ROUTES_TO {type: 'sync'}]->(payment)
CREATE (apigw)-[:ROUTES_TO {type: 'sync'}]->(cart)
CREATE (apigw)-[:ROUTES_TO {type: 'sync'}]->(inventory)
CREATE (apigw)-[:ROUTES_TO {type: 'sync'}]->(shipping)
CREATE (apigw)-[:ROUTES_TO {type: 'sync'}]->(user)
CREATE (apigw)-[:ROUTES_TO {type: 'sync'}]->(search)
CREATE (apigw)-[:ROUTES_TO {type: 'sync'}]->(notify)
CREATE (apigw)-[:ROUTES_TO {type: 'sync'}]->(pricing)
CREATE (apigw)-[:ROUTES_TO {type: 'sync'}]->(recommend)

// --- API Gateway shared dependencies ---
CREATE (apigw)-[:DEPENDS_ON {type: 'sync', criticality: 'critical'}]->(auth)
CREATE (apigw)-[:DEPENDS_ON {type: 'sync', criticality: 'critical'}]->(ratelimit)
CREATE (apigw)-[:DEPENDS_ON {type: 'config', criticality: 'degraded'}]->(config)
CREATE (apigw)-[:DEPENDS_ON {type: 'sync', criticality: 'critical'}]->(mesh)

// --- Order Service ---
CREATE (order)-[:DEPENDS_ON {type: 'sync', criticality: 'critical'}]->(pgpri)
CREATE (order)-[:DEPENDS_ON {type: 'sync', criticality: 'critical'}]->(payment)
CREATE (order)-[:DEPENDS_ON {type: 'sync', criticality: 'critical'}]->(inventory)
CREATE (order)-[:DEPENDS_ON {type: 'async', criticality: 'degraded'}]->(kafka)
CREATE (order)-[:DEPENDS_ON {type: 'async', criticality: 'degraded'}]->(notify)
CREATE (order)-[:DEPENDS_ON {type: 'cache', criticality: 'degraded'}]->(redis2)
CREATE (order)-[:DEPENDS_ON {type: 'sync', criticality: 'critical'}]->(auth)
CREATE (order)-[:DEPENDS_ON {type: 'config', criticality: 'degraded'}]->(config)
CREATE (order)-[:DEPENDS_ON {type: 'sync', criticality: 'critical'}]->(vault)
CREATE (order)-[:DEPENDS_ON {type: 'async', criticality: 'optional'}]->(audit)

// --- Payment Service ---
CREATE (payment)-[:DEPENDS_ON {type: 'sync', criticality: 'critical'}]->(pgpri)
CREATE (payment)-[:DEPENDS_ON {type: 'sync', criticality: 'critical'}]->(stripe)
CREATE (payment)-[:DEPENDS_ON {type: 'async', criticality: 'degraded'}]->(kafka)
CREATE (payment)-[:DEPENDS_ON {type: 'cache', criticality: 'degraded'}]->(redis2)
CREATE (payment)-[:DEPENDS_ON {type: 'sync', criticality: 'critical'}]->(auth)
CREATE (payment)-[:DEPENDS_ON {type: 'config', criticality: 'degraded'}]->(config)
CREATE (payment)-[:DEPENDS_ON {type: 'sync', criticality: 'critical'}]->(vault)

// --- Cart Service ---
CREATE (cart)-[:DEPENDS_ON {type: 'cache', criticality: 'critical'}]->(redis2)
CREATE (cart)-[:DEPENDS_ON {type: 'sync', criticality: 'degraded'}]->(pricing)
CREATE (cart)-[:DEPENDS_ON {type: 'sync', criticality: 'degraded'}]->(inventory)
CREATE (cart)-[:DEPENDS_ON {type: 'sync', criticality: 'critical'}]->(auth)
CREATE (cart)-[:DEPENDS_ON {type: 'config', criticality: 'degraded'}]->(config)

// --- Inventory Service ---
CREATE (inventory)-[:DEPENDS_ON {type: 'sync', criticality: 'critical'}]->(pgpri)
CREATE (inventory)-[:DEPENDS_ON {type: 'async', criticality: 'degraded'}]->(kafka)
CREATE (inventory)-[:DEPENDS_ON {type: 'cache', criticality: 'degraded'}]->(redis2)
CREATE (inventory)-[:DEPENDS_ON {type: 'sync', criticality: 'critical'}]->(auth)
CREATE (inventory)-[:DEPENDS_ON {type: 'config', criticality: 'degraded'}]->(config)

// --- Shipping Service ---
CREATE (shipping)-[:DEPENDS_ON {type: 'sync', criticality: 'critical'}]->(carrier)
CREATE (shipping)-[:DEPENDS_ON {type: 'sync', criticality: 'critical'}]->(pgpri)
CREATE (shipping)-[:DEPENDS_ON {type: 'async', criticality: 'degraded'}]->(kafka)
CREATE (shipping)-[:DEPENDS_ON {type: 'sync', criticality: 'critical'}]->(auth)
CREATE (shipping)-[:DEPENDS_ON {type: 'config', criticality: 'degraded'}]->(config)
CREATE (shipping)-[:DEPENDS_ON {type: 'sync', criticality: 'critical'}]->(vault)

// --- User / Account Service ---
CREATE (user)-[:DEPENDS_ON {type: 'sync', criticality: 'critical'}]->(pgpri)
CREATE (user)-[:DEPENDS_ON {type: 'cache', criticality: 'degraded'}]->(redis1)
CREATE (user)-[:DEPENDS_ON {type: 'config', criticality: 'degraded'}]->(config)
CREATE (user)-[:DEPENDS_ON {type: 'sync', criticality: 'critical'}]->(vault)

// --- Search Service ---
CREATE (search)-[:DEPENDS_ON {type: 'sync', criticality: 'critical'}]->(elastic)
CREATE (search)-[:DEPENDS_ON {type: 'cache', criticality: 'degraded'}]->(redis2)
CREATE (search)-[:DEPENDS_ON {type: 'config', criticality: 'degraded'}]->(config)

// --- Notification Service ---
CREATE (notify)-[:DEPENDS_ON {type: 'async', criticality: 'critical'}]->(kafka)
CREATE (notify)-[:DEPENDS_ON {type: 'async', criticality: 'degraded'}]->(rabbit)
CREATE (notify)-[:DEPENDS_ON {type: 'sync', criticality: 'critical'}]->(sendgrid)
CREATE (notify)-[:DEPENDS_ON {type: 'sync', criticality: 'critical'}]->(sms)
CREATE (notify)-[:DEPENDS_ON {type: 'sync', criticality: 'degraded'}]->(mongo)
CREATE (notify)-[:DEPENDS_ON {type: 'cache', criticality: 'degraded'}]->(redis1)
CREATE (notify)-[:DEPENDS_ON {type: 'config', criticality: 'degraded'}]->(config)

// --- Pricing Service ---
CREATE (pricing)-[:DEPENDS_ON {type: 'sync', criticality: 'degraded'}]->(pgrep)
CREATE (pricing)-[:DEPENDS_ON {type: 'cache', criticality: 'degraded'}]->(redis2)
CREATE (pricing)-[:DEPENDS_ON {type: 'sync', criticality: 'degraded'}]->(taxapi)
CREATE (pricing)-[:DEPENDS_ON {type: 'config', criticality: 'degraded'}]->(config)
CREATE (pricing)-[:DEPENDS_ON {type: 'sync', criticality: 'degraded'}]->(flagsvc)

// --- Recommendation Service ---
CREATE (recommend)-[:DEPENDS_ON {type: 'sync', criticality: 'critical'}]->(elastic)
CREATE (recommend)-[:DEPENDS_ON {type: 'cache', criticality: 'degraded'}]->(redis2)
CREATE (recommend)-[:DEPENDS_ON {type: 'sync', criticality: 'critical'}]->(mlmodel)
CREATE (recommend)-[:DEPENDS_ON {type: 'config', criticality: 'degraded'}]->(config)
CREATE (recommend)-[:DEPENDS_ON {type: 'sync', criticality: 'degraded'}]->(flagsvc)

// --- Auth / IAM ---
CREATE (auth)-[:DEPENDS_ON {type: 'sync', criticality: 'critical'}]->(vault)
CREATE (auth)-[:DEPENDS_ON {type: 'cache', criticality: 'degraded'}]->(redis1)
CREATE (auth)-[:DEPENDS_ON {type: 'sync', criticality: 'critical'}]->(pgpri)
CREATE (auth)-[:DEPENDS_ON {type: 'config', criticality: 'degraded'}]->(config)

// --- Config Service ---
CREATE (config)-[:DEPENDS_ON {type: 'sync', criticality: 'critical'}]->(vault)
CREATE (config)-[:DEPENDS_ON {type: 'sync', criticality: 'degraded'}]->(s3)

// --- Rate Limiter ---
CREATE (ratelimit)-[:DEPENDS_ON {type: 'sync', criticality: 'critical'}]->(redis2)
CREATE (ratelimit)-[:DEPENDS_ON {type: 'config', criticality: 'degraded'}]->(config)

// --- Audit Logger ---
CREATE (audit)-[:DEPENDS_ON {type: 'async', criticality: 'degraded'}]->(kafka)
CREATE (audit)-[:DEPENDS_ON {type: 'sync', criticality: 'degraded'}]->(elastic)
CREATE (audit)-[:DEPENDS_ON {type: 'config', criticality: 'degraded'}]->(config)

// --- Feature Flag Service ---
CREATE (flagsvc)-[:DEPENDS_ON {type: 'sync', criticality: 'degraded'}]->(pgrep)
CREATE (flagsvc)-[:DEPENDS_ON {type: 'cache', criticality: 'degraded'}]->(redis1)
CREATE (flagsvc)-[:DEPENDS_ON {type: 'config', criticality: 'degraded'}]->(config)

// --- ML Model Service ---
CREATE (mlmodel)-[:DEPENDS_ON {type: 'sync', criticality: 'critical'}]->(s3)
CREATE (mlmodel)-[:DEPENDS_ON {type: 'cache', criticality: 'degraded'}]->(redis2)
CREATE (mlmodel)-[:DEPENDS_ON {type: 'config', criticality: 'degraded'}]->(config)

// --- PG Read Replica replicates from Primary ---
CREATE (pgrep)-[:REPLICATES_FROM {type: 'async', criticality: 'critical'}]->(pgpri)

// --- External services depend on DNS ---
CREATE (stripe)-[:DEPENDS_ON {type: 'sync', criticality: 'critical'}]->(dns)
CREATE (carrier)-[:DEPENDS_ON {type: 'sync', criticality: 'critical'}]->(dns)
CREATE (sendgrid)-[:DEPENDS_ON {type: 'sync', criticality: 'critical'}]->(dns)
CREATE (sms)-[:DEPENDS_ON {type: 'sync', criticality: 'critical'}]->(dns)
CREATE (taxapi)-[:DEPENDS_ON {type: 'sync', criticality: 'critical'}]->(dns);

// ============================================================
// Indexes for fast lookup
// ============================================================
CREATE INDEX service_id IF NOT EXISTS FOR (s:Service) ON (s.id);
CREATE INDEX service_name IF NOT EXISTS FOR (s:Service) ON (s.name);
CREATE INDEX service_layer IF NOT EXISTS FOR (s:Service) ON (s.layer);
CREATE INDEX service_team IF NOT EXISTS FOR (s:Service) ON (s.team);
