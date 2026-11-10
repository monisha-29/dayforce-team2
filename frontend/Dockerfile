# Dev-server image: the same server you run locally with `npm run dev`.
FROM node:22-slim

WORKDIR /app

COPY package.json ./
# The project is built with bun; npm needs --legacy-peer-deps to resolve it
RUN npm install --legacy-peer-deps

COPY . .

# Read by Vite when the server starts (the browser talks to the API on the host's port 8000)
ENV VITE_USE_MOCK_API=false \
    VITE_API_BASE_URL=http://localhost:8000/api/v1

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]
