package dev.jadenfix.androidbridge;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.BufferedWriter;
import java.io.InputStreamReader;
import java.io.OutputStreamWriter;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;

final class BridgeServer extends Thread {
    static final int DEVICE_PORT = 6210;
    static final int MAX_REQUEST_CHARS = 1_000_000;

    private final BridgeAccessibilityService service;
    private volatile boolean closed;
    private volatile ServerSocket listener;

    BridgeServer(BridgeAccessibilityService service) {
        super("android-agent-bridge");
        setDaemon(true);
        this.service = service;
    }

    @Override
    public void run() {
        try (ServerSocket server = new ServerSocket()) {
            listener = server;
            server.setReuseAddress(true);
            server.bind(new InetSocketAddress(InetAddress.getLoopbackAddress(), DEVICE_PORT));
            while (!closed) {
                try {
                    Socket client = server.accept();
                    client.setTcpNoDelay(true);
                    handleClient(client);
                } catch (Exception ignored) {
                    if (closed) return;
                }
            }
        } catch (Exception ignored) {
            // Host health checks expose startup/bind failures without creating a public log surface.
        } finally {
            listener = null;
        }
    }

    void close() {
        closed = true;
        ServerSocket current = listener;
        if (current != null) {
            try {
                current.close();
            } catch (Exception ignored) {
            }
        }
        interrupt();
    }

    private void handleClient(Socket socket) {
        try (Socket client = socket;
             BufferedReader reader = new BufferedReader(new InputStreamReader(client.getInputStream(), StandardCharsets.UTF_8));
             BufferedWriter writer = new BufferedWriter(new OutputStreamWriter(client.getOutputStream(), StandardCharsets.UTF_8))) {
            String line;
            while (!closed && (line = reader.readLine()) != null) {
                JSONObject response;
                if (line.length() > MAX_REQUEST_CHARS) {
                    response = error(null, "request too large");
                } else {
                    try {
                        response = dispatch(new JSONObject(line));
                    } catch (Exception exc) {
                        response = error(null, safeMessage(exc));
                    }
                }
                writer.write(response.toString());
                writer.write('\n');
                writer.flush();
            }
        } catch (Exception ignored) {
        }
    }

    private JSONObject dispatch(JSONObject request) throws Exception {
        Object requestId = request.opt("id");
        String expectedToken = service.readToken();
        String suppliedToken = request.optString("token", "");
        if (expectedToken.length() < 32 || !constantTimeEquals(expectedToken, suppliedToken)) {
            return error(requestId, "unauthorized");
        }

        String op = request.optString("op", "");
        JSONObject result = new JSONObject();
        switch (op) {
            case "health":
                result.put("service", "android-agent-bridge");
                result.put("protocol", 1);
                result.put("revision", service.currentRevision());
                break;
            case "observe":
                result = service.observe();
                break;
            case "act": {
                long expectedRevision = request.optLong("expected_revision", 0L);
                long actualRevision = service.currentRevision();
                if (expectedRevision > 0L && expectedRevision != actualRevision) {
                    result.put("stale", true);
                    result.put("expected_revision", expectedRevision);
                    result.put("revision", actualRevision);
                    result.put("observation", service.observe());
                    break;
                }
                JSONArray actions = request.optJSONArray("actions");
                if (actions == null) throw new IllegalArgumentException("actions must be an array");
                result.put("results", service.executeActions(actions));
                result.put("revision", service.currentRevision());
                break;
            }
            case "act_observe": {
                long expectedRevision = request.optLong("expected_revision", 0L);
                long actualRevision = service.currentRevision();
                if (expectedRevision > 0L && expectedRevision != actualRevision) {
                    result.put("stale", true);
                    result.put("expected_revision", expectedRevision);
                    result.put("revision", actualRevision);
                    result.put("observation", service.observe());
                    break;
                }
                JSONArray actions = request.optJSONArray("actions");
                if (actions == null) throw new IllegalArgumentException("actions must be an array");
                long before = service.currentRevision();
                result.put("results", service.executeActions(actions));
                long timeoutMs = Math.max(0L, Math.min(5_000L, request.optLong("timeout_ms", 900L)));
                result.put("changed", service.waitForRevision(before, timeoutMs));
                result.put("observation", service.observe());
                break;
            }
            case "wait_observe": {
                long after = request.optLong("after_revision", service.currentRevision());
                long timeoutMs = Math.max(0L, Math.min(15_000L, request.optLong("timeout_ms", 2_000L)));
                result.put("changed", service.waitForRevision(after, timeoutMs));
                result.put("observation", service.observe());
                break;
            }
            case "screenshot":
                result.put("png_base64", service.screenshotBase64());
                result.put("revision", service.currentRevision());
                break;
            default:
                throw new IllegalArgumentException("unsupported operation: " + op);
        }
        return ok(requestId, result);
    }

    private static JSONObject ok(Object id, JSONObject result) throws Exception {
        JSONObject response = new JSONObject();
        if (id != null) response.put("id", id);
        response.put("ok", true);
        response.put("result", result);
        return response;
    }

    private static JSONObject error(Object id, String message) {
        JSONObject response = new JSONObject();
        try {
            if (id != null) response.put("id", id);
            response.put("ok", false);
            response.put("error", message);
        } catch (Exception ignored) {
        }
        return response;
    }

    private static boolean constantTimeEquals(String expected, String actual) {
        return MessageDigest.isEqual(
                expected.getBytes(StandardCharsets.UTF_8),
                actual.getBytes(StandardCharsets.UTF_8));
    }

    private static String safeMessage(Exception exception) {
        String message = exception.getMessage();
        if (message == null || message.isEmpty()) return exception.getClass().getSimpleName();
        return message.length() > 500 ? message.substring(0, 500) : message;
    }
}
