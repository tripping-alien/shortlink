    document.addEventListener('DOMContentLoaded', () => {
     const canvas = document.getElementById('background-animation');
     if (!canvas) return;

     const gl = canvas.getContext('webgl');
     if (!gl) {
         console.warn("WebGL not supported, background animation disabled.");
         return;
     }

    const vertexShaderSource = `
        attribute vec2 a_position;
        void main() {
            gl_Position = vec4(a_position, 0.0, 1.0);
        }
    `;

    const fragmentShaderSource = `
        precision mediump float;
        uniform vec2 u_resolution;
        uniform float u_time;
        
        // Function to create a layer of moving lines
        float line_layer(vec2 st, float speed, float density, float angle) {
            // Rotate coordinates
            float s = sin(angle);
            float c = cos(angle);
            mat2 rotation_matrix = mat2(c, -s, s, c);
            st = rotation_matrix * st;
            
            // Create repeating lines
            float line = fract((st.x + u_time * speed) * density);
            
            // Make the line smooth and fade it out
            return smoothstep(0.9, 0.8, line);
        }

        void main() {
            vec2 st = gl_FragCoord.xy / u_resolution.xy;
            // Create three layers of lines with different speeds, densities, and opacities
            float layer1 = line_layer(st, 0.05, 5.0, 0.785) * 0.1;  // 45 degrees
            float layer2 = line_layer(st, 0.08, 7.0, 0.785) * 0.05;
            float layer3 = line_layer(st, -0.06, 6.0, -0.785) * 0.08; // -45 degrees
            vec3 color = vec3(1.0, 0.655, 0.149) * (layer1 + layer2 + layer3); // Sunshine Orange: rgb(255, 167, 38)

            gl_FragColor = vec4(color, 1.0);
        }
    `;

    function createShader(gl, type, source) {
        const shader = gl.createShader(type);
        gl.shaderSource(shader, source);
        gl.compileShader(shader);
        if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
            console.error('Shader compile error:', gl.getShaderInfoLog(shader));
            gl.deleteShader(shader);
            return null;
        }
        return shader;
    }

    const vertexShader = createShader(gl, gl.VERTEX_SHADER, vertexShaderSource);
    const fragmentShader = createShader(gl, gl.FRAGMENT_SHADER, fragmentShaderSource);
    const program = gl.createProgram();
    gl.attachShader(program, vertexShader);
    gl.attachShader(program, fragmentShader);
    gl.linkProgram(program);
    gl.useProgram(program);

    const positionBuffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, positionBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, 1]), gl.STATIC_DRAW);

    const positionAttributeLocation = gl.getAttribLocation(program, "a_position");
    gl.enableVertexAttribArray(positionAttributeLocation);
    gl.vertexAttribPointer(positionAttributeLocation, 2, gl.FLOAT, false, 0, 0);

    const resolutionUniformLocation = gl.getUniformLocation(program, "u_resolution");
    const timeUniformLocation = gl.getUniformLocation(program, "u_time");

    function render(time) {
        time *= 0.001; // convert to seconds

        const displayWidth = canvas.clientWidth;
        const displayHeight = canvas.clientHeight;

        if (canvas.width !== displayWidth || canvas.height !== displayHeight) {
            canvas.width = displayWidth;
            canvas.height = displayHeight;
            gl.viewport(0, 0, canvas.width, canvas.height);
        }

        gl.uniform2f(resolutionUniformLocation, gl.canvas.width, gl.canvas.height);
        gl.uniform1f(timeUniformLocation, time);

        gl.drawArrays(gl.TRIANGLES, 0, 6);

        requestAnimationFrame(render);
    }

    requestAnimationFrame(render);
});