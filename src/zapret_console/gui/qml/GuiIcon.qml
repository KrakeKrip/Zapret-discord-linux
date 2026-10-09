import QtQuick

// Линейные иконки 24-сетка, линия 1.8 px (design/gui-v1/SPEC.md).
Canvas {
    id: icon
    property string name: ""
    property color color: Theme.muted
    width: 22
    height: 22
    antialiasing: true

    onNameChanged: requestPaint()
    onColorChanged: requestPaint()
    onWidthChanged: requestPaint()

    onPaint: {
        var ctx = getContext('2d');
        ctx.reset();
        ctx.clearRect(0, 0, width, height);
        ctx.strokeStyle = String(color);
        ctx.lineWidth = 1.8;
        ctx.lineCap = 'round';
        ctx.lineJoin = 'round';
        ctx.save();
        ctx.scale(width / 24, height / 24);
        ctx.beginPath();
        if (name === 'home') {
            ctx.moveTo(3, 10);
            ctx.lineTo(12, 3);
            ctx.lineTo(21, 10);
            ctx.lineTo(21, 20);
            ctx.lineTo(15, 20);
            ctx.lineTo(15, 14);
            ctx.lineTo(9, 14);
            ctx.lineTo(9, 20);
            ctx.lineTo(3, 20);
            ctx.closePath();
        } else if (name === 'folder') {
            ctx.moveTo(3, 6);
            ctx.lineTo(10, 6);
            ctx.lineTo(12, 9);
            ctx.lineTo(21, 9);
            ctx.lineTo(21, 20);
            ctx.lineTo(3, 20);
            ctx.closePath();
        } else if (name === 'tune') {
            ctx.moveTo(4, 6);
            ctx.lineTo(20, 6);
            ctx.moveTo(4, 12);
            ctx.lineTo(20, 12);
            ctx.moveTo(4, 18);
            ctx.lineTo(20, 18);
            ctx.moveTo(9, 3);
            ctx.lineTo(9, 9);
            ctx.moveTo(16, 9);
            ctx.lineTo(16, 15);
            ctx.moveTo(8, 15);
            ctx.lineTo(8, 21);
        } else if (name === 'power') {
            ctx.moveTo(12, 2.5);
            ctx.lineTo(12, 11.5);
            ctx.stroke();
            ctx.beginPath();
            ctx.arc(12, 12.8, 8.3, -Math.PI / 2 + 0.6, 3 * Math.PI / 2 - 0.6);
        } else if (name === 'search') {
            ctx.arc(10, 10, 7.5, 0, 2 * Math.PI);
            ctx.moveTo(15.8, 15.8);
            ctx.lineTo(21, 21);
        } else if (name === 'check') {
            ctx.moveTo(4, 12);
            ctx.lineTo(9, 17);
            ctx.lineTo(20, 6);
        }
        ctx.stroke();
        ctx.restore();
    }
}
