FROM node:20-bookworm-slim AS frontend_builder

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 make g++ \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build/frontend

# 前端构建时需要的 Vite 环境变量（通过 build args 传入）
ARG VITE_SUPABASE_URL
ARG VITE_SUPABASE_ANON_KEY

COPY agent-web-fronted/package.json agent-web-fronted/package-lock.json ./
COPY agent-web-fronted/index.html ./
COPY agent-web-fronted/tsconfig.json ./
COPY agent-web-fronted/vite.config.ts ./
COPY agent-web-fronted/.env* ./

COPY agent-web-fronted/scripts ./scripts
COPY agent-web-fronted/src ./src

# 写入 .env 供 Vite 构建使用
RUN if [ -n "$VITE_SUPABASE_URL" ]; then \
      echo "VITE_SUPABASE_URL=$VITE_SUPABASE_URL" > .env && \
      echo "VITE_SUPABASE_ANON_KEY=$VITE_SUPABASE_ANON_KEY" >> .env; \
    fi

RUN npm install --force --platform=linux
RUN npm run build

FROM openresty/openresty:alpine-fat

# 安装 CA 证书，供 JWKS HTTPS 拉取校验使用
RUN apk add --no-cache ca-certificates

# 安装 JWKS/JWT 校验依赖
RUN /usr/local/openresty/bin/opm get ledgetech/lua-resty-http \
    && /usr/local/openresty/bin/opm get fffonion/lua-resty-openssl \
    && /usr/local/openresty/bin/opm get anvouk/lua-resty-jwt-verification

# 避免 nginx 写文件日志时报 /var/log/nginx/error.log 不存在
RUN mkdir -p /var/log/nginx \
    && ln -sf /dev/stdout /var/log/nginx/access.log \
    && ln -sf /dev/stderr /var/log/nginx/error.log

# 创建 SSL 证书目录
RUN mkdir -p /etc/nginx/ssl

COPY --from=frontend_builder /build/frontend/dist/ /usr/local/openresty/nginx/html/
