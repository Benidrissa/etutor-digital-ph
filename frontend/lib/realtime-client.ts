/**
 * Thin wrapper over the OpenAI Realtime WebRTC flow (#1932).
 *
 * The backend mints an ephemeral client_secret via /tutor/voice-session;
 * the browser then POSTs an SDP offer to OpenAI with that token, receives
 * an answer, and sets up bidirectional audio through a peer connection.
 *
 * We only surface the pieces the modal needs: the peer connection (for
 * track tracking), the mic stream (for mute), the remote <audio> element
 * (for playback), the data channel (for future fine-grained events), and
 * a shutdown function that closes everything cleanly.
 */

export interface RealtimeConnection {
  peerConnection: RTCPeerConnection;
  dataChannel: RTCDataChannel;
  micStream: MediaStream;
  remoteAudio: HTMLAudioElement;
  close: () => void;
}

export interface RealtimeConnectOptions {
  clientSecret: string;
  model: string;
  onConnected?: () => void;
  onError?: (err: Error) => void;
}

export async function connectRealtime(
  opts: RealtimeConnectOptions
): Promise<RealtimeConnection> {
  const pc = new RTCPeerConnection();

  const remoteAudio = document.createElement('audio');
  remoteAudio.autoplay = true;
  pc.ontrack = (event) => {
    if (event.streams[0]) {
      remoteAudio.srcObject = event.streams[0];
    }
  };

  const micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
  micStream.getTracks().forEach((track) => pc.addTrack(track, micStream));

  const dataChannel = pc.createDataChannel('oai-events');

  const offer = await pc.createOffer();
  await pc.setLocalDescription(offer);

  const response = await fetch(
    `https://api.openai.com/v1/realtime?model=${encodeURIComponent(opts.model)}`,
    {
      method: 'POST',
      body: offer.sdp,
      headers: {
        Authorization: `Bearer ${opts.clientSecret}`,
        'Content-Type': 'application/sdp',
      },
    }
  );

  if (!response.ok) {
    pc.close();
    micStream.getTracks().forEach((t) => t.stop());
    const body = await response.text().catch(() => '');
    throw new Error(
      `OpenAI Realtime handshake failed (${response.status}): ${body.slice(0, 200)}`
    );
  }

  const answerSdp = await response.text();
  await pc.setRemoteDescription({ type: 'answer', sdp: answerSdp });

  pc.onconnectionstatechange = () => {
    if (pc.connectionState === 'connected') {
      opts.onConnected?.();
    } else if (pc.connectionState === 'failed') {
      opts.onError?.(new Error('WebRTC connection failed'));
    }
  };

  const close = () => {
    try {
      dataChannel.close();
    } catch {
      // no-op
    }
    try {
      micStream.getTracks().forEach((t) => t.stop());
    } catch {
      // no-op
    }
    try {
      pc.close();
    } catch {
      // no-op
    }
    remoteAudio.pause();
    remoteAudio.srcObject = null;
  };

  return { peerConnection: pc, dataChannel, micStream, remoteAudio, close };
}
