# Tigrit Web: сборка фронта (Vite), nginx раздаёт dist и проксирует /api на tigrit-api
FROM node:20-alpine AS front
WORKDIR /app
COPY frontend/package*.json frontend/
RUN cd frontend && npm ci
COPY frontend/ frontend/
RUN cd frontend && npm run build

FROM nginx:alpine
COPY --from=front /app/frontend/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
