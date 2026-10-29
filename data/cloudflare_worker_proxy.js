/**
 * SOI REVIEW - CLOUDFLARE WORKER REVERSE PROXY
 * ==============================================================================
 * Worker này được triển khai trên mạng lưới Cloudflare Global Edge (miễn phí 100k req/ngày).
 * Giúp Soi Review vượt tường lửa, chống chặn IP khi cào dữ liệu từ Shopee / BeeCost / Tiki.
 * 
 * Hướng dẫn triển khai (chưa đầy 1 phút):
 * 1. Truy cập https://dash.cloudflare.com -> Chọn "Workers & Pages" -> "Create Application".
 * 2. Chọn "Create Worker" -> Đặt tên (ví dụ: `soi-review-proxy`).
 * 3. Dán toàn bộ nội dung file này vào editor -> Bấm "Deploy".
 * 4. Copy URL của Worker (ví dụ: `https://soi-review-proxy.xxx.workers.dev`) và dán vào
 *    biến `CLOUDFLARE_WORKER_PROXY_URL` trong file `.env` của backend.
 * ==============================================================================
 */

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    // 0. Kiểm tra mã khóa bí mật nội bộ chống biến Worker thành Open Proxy
    const expectedSecret = (env && env.WORKER_SECRET) ? env.WORKER_SECRET : "soireview_worker_edge_2026";
    const clientSecret = request.headers.get("X-SoiReview-Secret");
    if (clientSecret !== expectedSecret) {
      return new Response(JSON.stringify({
        status: "unauthorized",
        message: "Cảnh báo bảo mật: Yêu cầu không có khóa bí mật nội bộ X-SoiReview-Secret hợp lệ."
      }), {
        status: 401,
        headers: { "Content-Type": "application/json; charset=utf-8", "Access-Control-Allow-Origin": "*" }
      });
    }

    // Endpoint: Hỗ trợ Native Workers AI (Llama 3.1) nếu có cấu hình binding 'AI'
    if (url.pathname.startsWith("/ai") && request.method === "POST") {
      try {
        const body = await request.json();
        const prompt = body.prompt || "";
        if (env && env.AI) {
          const aiResponse = await env.AI.run("@cf/meta/llama-3.1-8b-instruct", {
            messages: [
              { role: "system", content: "You are an expert product reviewer and anti-fake auditor. Return ONLY valid JSON." },
              { role: "user", content: prompt }
            ]
          });
          return new Response(JSON.stringify(aiResponse), {
            status: 200,
            headers: { "Content-Type": "application/json; charset=utf-8", "Access-Control-Allow-Origin": "*" }
          });
        } else {
          return new Response(JSON.stringify({ error: "Workers AI binding 'AI' is not configured on this Worker." }), {
            status: 503,
            headers: { "Content-Type": "application/json; charset=utf-8", "Access-Control-Allow-Origin": "*" }
          });
        }
      } catch (err) {
        return new Response(JSON.stringify({ error: err.message }), {
          status: 500,
          headers: { "Content-Type": "application/json; charset=utf-8", "Access-Control-Allow-Origin": "*" }
        });
      }
    }

    // 1. Chỉ cho phép các request có query parameter ?url=...
    const targetUrl = url.searchParams.get("url");

    if (!targetUrl) {
      return new Response(JSON.stringify({
        status: "error",
        message: "Soi Review Cloudflare Edge Proxy is active. Please provide a target URL via ?url=..."
      }), {
        status: 400,
        headers: {
          "Content-Type": "application/json; charset=utf-8",
          "Access-Control-Allow-Origin": "*"
        }
      });
    }

    // 2. Chuẩn bị Headers cho request chuyển tiếp
    const forwardHeaders = new Headers(request.headers);
    forwardHeaders.set("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36");
    forwardHeaders.set("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8");
    forwardHeaders.set("Accept-Language", "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7");
    forwardHeaders.delete("host");

    try {
      // 3. Gọi request đến target URL từ Edge Server của Cloudflare
      const response = await fetch(targetUrl, {
        method: request.method,
        headers: forwardHeaders,
        body: request.method !== "GET" && request.method !== "HEAD" ? request.body : undefined,
        redirect: "follow"
      });

      // 4. Trả kết quả về với header CORS đầy đủ
      const responseHeaders = new Headers(response.headers);
      responseHeaders.set("Access-Control-Allow-Origin", "*");
      responseHeaders.set("X-Proxied-By", "Soi-Review-Cloudflare-Edge");

      return new Response(response.body, {
        status: response.status,
        headers: responseHeaders
      });
    } catch (err) {
      return new Response(JSON.stringify({
        status: "proxy_error",
        error: err.message
      }), {
        status: 502,
        headers: {
          "Content-Type": "application/json; charset=utf-8",
          "Access-Control-Allow-Origin": "*"
        }
      });
    }
  }
};
