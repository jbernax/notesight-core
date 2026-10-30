FROM node:22-alpine as build-stage

WORKDIR /app

COPY package*.json ./
RUN npm install

COPY . .
RUN npm run build

# Use Nginx to serve the static frontend
FROM nginx:alpine as production-stage
COPY --from=build-stage /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Ensure unprivileged user ownership for static assets and pidfile
RUN touch /var/run/nginx.pid && \
    chown -R nginx:nginx /var/run/nginx.pid /usr/share/nginx/html /var/cache/nginx /var/log/nginx

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
