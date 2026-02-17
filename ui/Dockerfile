FROM node:20-alpine
WORKDIR /app

COPY ui/package.json ui/package-lock.json* ./
RUN npm ci || npm install

COPY ui/ ./
EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]
