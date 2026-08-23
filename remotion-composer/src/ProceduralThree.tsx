import React, {useMemo} from "react";
import {ThreeCanvas} from "@remotion/three";
import {
  AbsoluteFill,
  Easing,
  interpolate,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

export type ThreeTemplateId =
  | "ui-depth-stack"
  | "orbital-reveal"
  | "data-constellation";

export interface ThreeSceneSpec {
  version: "1.0";
  id: string;
  template_id: ThreeTemplateId;
  duration_frames: number;
  fps: number;
  width: number;
  height: number;
  seed: number;
  theme: {
    background: string;
    primary: string;
    accent: string;
    foreground: string;
  };
  camera?: {position?: [number, number, number]; fov?: number};
  lighting?: {ambient?: number; key?: number};
  content?: {title?: string; subtitle?: string};
  beat_cue_frames?: number[];
}

export type ProceduralThreeProps = {
  sceneSpec: ThreeSceneSpec;
};

const mulberry32 = (seed: number) => {
  let state = seed >>> 0;
  return () => {
    state += 0x6d2b79f5;
    let value = state;
    value = Math.imul(value ^ (value >>> 15), value | 1);
    value ^= value + Math.imul(value ^ (value >>> 7), value | 61);
    return ((value ^ (value >>> 14)) >>> 0) / 4294967296;
  };
};

const cuePulseAt = (frame: number, cues: number[]) =>
  cues.reduce((peak, cue) => {
    const distance = Math.abs(frame - cue);
    const pulse = interpolate(distance, [0, 9], [1, 0], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
      easing: Easing.out(Easing.quad),
    });
    return Math.max(peak, pulse);
  }, 0);

const UiDepthStack: React.FC<{
  spec: ThreeSceneSpec;
  progress: number;
  pulse: number;
}> = ({spec, progress, pulse}) => {
  const cards = useMemo(() => {
    const random = mulberry32(spec.seed);
    return Array.from({length: 7}, (_, index) => ({
      x: (random() - 0.5) * 4.8,
      y: (index - 3) * 0.58,
      z: -index * 0.46,
      width: 3.4 + random() * 1.8,
    }));
  }, [spec.seed]);
  const reveal = interpolate(progress, [0, 0.22], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });
  return (
    <group rotation={[0.13, -0.24 + progress * 0.18, -0.08]}>
      {cards.map((card, index) => {
        const local = Math.max(0, Math.min(1, reveal * 1.5 - index * 0.08));
        return (
          <mesh
            key={index}
            position={[card.x * 0.12 * local, card.y, card.z + (1 - local) * -4]}
            scale={[local * (1 + pulse * 0.035), local, local]}
          >
            <boxGeometry args={[card.width, 0.38, 0.18]} />
            <meshStandardMaterial
              color={index % 3 === 0 ? spec.theme.accent : spec.theme.primary}
              roughness={0.35}
              metalness={0.18}
            />
          </mesh>
        );
      })}
    </group>
  );
};

const OrbitalReveal: React.FC<{
  spec: ThreeSceneSpec;
  frame: number;
  progress: number;
  pulse: number;
}> = ({spec, frame, progress, pulse}) => {
  const satellites = useMemo(() => {
    const random = mulberry32(spec.seed);
    return Array.from({length: 12}, (_, index) => ({
      radius: 2.1 + random() * 1.35,
      angle: (index / 12) * Math.PI * 2 + random() * 0.35,
      y: (random() - 0.5) * 2.8,
      size: 0.07 + random() * 0.12,
    }));
  }, [spec.seed]);
  const entrance = interpolate(progress, [0, 0.2], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.exp),
  });
  return (
    <group rotation={[0.18, progress * Math.PI * 0.48, -0.12]}>
      <mesh scale={entrance * (1 + pulse * 0.09)}>
        <icosahedronGeometry args={[1.05, 4]} />
        <meshStandardMaterial color={spec.theme.primary} roughness={0.18} metalness={0.55} />
      </mesh>
      <mesh rotation={[Math.PI / 2.5, 0, frame * 0.004]} scale={entrance}>
        <torusGeometry args={[2.1, 0.045, 16, 128]} />
        <meshStandardMaterial color={spec.theme.accent} emissive={spec.theme.accent} emissiveIntensity={0.45} />
      </mesh>
      {satellites.map((satellite, index) => {
        const angle = satellite.angle + progress * (0.55 + (index % 3) * 0.12);
        return (
          <mesh
            key={index}
            position={[
              Math.cos(angle) * satellite.radius * entrance,
              satellite.y * entrance,
              Math.sin(angle) * satellite.radius * entrance,
            ]}
            scale={1 + pulse * 0.15}
          >
            <sphereGeometry args={[satellite.size, 16, 16]} />
            <meshStandardMaterial color={index % 2 ? spec.theme.foreground : spec.theme.accent} emissive={spec.theme.accent} emissiveIntensity={0.3} />
          </mesh>
        );
      })}
    </group>
  );
};

const DataConstellation: React.FC<{
  spec: ThreeSceneSpec;
  progress: number;
  pulse: number;
}> = ({spec, progress, pulse}) => {
  const nodes = useMemo(() => {
    const random = mulberry32(spec.seed);
    return Array.from({length: 34}, (_, index) => ({
      x: (random() - 0.5) * 7.2,
      y: (random() - 0.5) * 4.4,
      z: (random() - 0.5) * 3.6,
      size: 0.045 + random() * 0.12,
      delay: index / 48,
    }));
  }, [spec.seed]);
  return (
    <group rotation={[progress * 0.12, -0.35 + progress * 0.42, 0]}>
      {nodes.map((node, index) => {
        const reveal = interpolate(progress, [node.delay, node.delay + 0.28], [0, 1], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
          easing: Easing.out(Easing.cubic),
        });
        return (
          <mesh
            key={index}
            position={[node.x * reveal, node.y * reveal, node.z * reveal]}
            scale={reveal * (1 + pulse * (index % 5 === 0 ? 0.35 : 0.08))}
          >
            <sphereGeometry args={[node.size, 14, 14]} />
            <meshStandardMaterial
              color={index % 4 === 0 ? spec.theme.accent : spec.theme.primary}
              emissive={index % 4 === 0 ? spec.theme.accent : spec.theme.primary}
              emissiveIntensity={0.55}
            />
          </mesh>
        );
      })}
    </group>
  );
};

export const ProceduralThree: React.FC<ProceduralThreeProps> = ({sceneSpec}) => {
  const frame = useCurrentFrame();
  const {width, height, durationInFrames} = useVideoConfig();
  const progress = frame / Math.max(1, durationInFrames - 1);
  const pulse = cuePulseAt(frame, sceneSpec.beat_cue_frames ?? []);
  const camera = sceneSpec.camera ?? {};
  const lighting = sceneSpec.lighting ?? {};
  const content = sceneSpec.content ?? {};

  return (
    <AbsoluteFill style={{backgroundColor: sceneSpec.theme.background}}>
      <ThreeCanvas
        width={width}
        height={height}
        camera={{
          position: camera.position ?? [0, 0, 8],
          fov: camera.fov ?? 42,
        }}
      >
        <ambientLight intensity={lighting.ambient ?? 0.48} />
        <directionalLight position={[5, 7, 8]} intensity={lighting.key ?? 1.35} />
        <pointLight position={[-5, -2, 4]} intensity={0.8 + pulse * 0.7} color={sceneSpec.theme.accent} />
        {sceneSpec.template_id === "ui-depth-stack" ? (
          <UiDepthStack spec={sceneSpec} progress={progress} pulse={pulse} />
        ) : sceneSpec.template_id === "orbital-reveal" ? (
          <OrbitalReveal spec={sceneSpec} frame={frame} progress={progress} pulse={pulse} />
        ) : (
          <DataConstellation spec={sceneSpec} progress={progress} pulse={pulse} />
        )}
      </ThreeCanvas>
      <AbsoluteFill
        style={{
          justifyContent: "flex-end",
          padding: "0 110px 92px",
          boxSizing: "border-box",
          color: sceneSpec.theme.foreground,
          fontFamily: "Inter, system-ui, sans-serif",
          pointerEvents: "none",
        }}
      >
        {content.title ? (
          <div style={{fontSize: 64, fontWeight: 720, letterSpacing: -2.4, opacity: interpolate(progress, [0.08, 0.24], [0, 1], {extrapolateRight: "clamp"})}}>
            {content.title}
          </div>
        ) : null}
        {content.subtitle ? (
          <div style={{fontSize: 27, marginTop: 14, color: sceneSpec.theme.accent, opacity: interpolate(progress, [0.16, 0.32], [0, 1], {extrapolateRight: "clamp"})}}>
            {content.subtitle}
          </div>
        ) : null}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
