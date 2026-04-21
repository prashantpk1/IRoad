const fs = require('fs');
let content = fs.readFileSync('Ticket-replies.html', 'utf8');
let newHtml = fs.readFileSync('temp_content.html', 'utf8');

const startTag = '<main class="main-content">';
const endTag = '</main>';

const startIndex = content.indexOf(startTag);
const endIndex = content.indexOf(endTag);

if (startIndex !== -1 && endIndex !== -1) {
  const newContent = content.substring(0, startIndex + startTag.length) + '\n' +
    newHtml + '\n' +
    content.substring(endIndex);
  fs.writeFileSync('Ticket-replies.html', newContent, 'utf8');
  console.log('Replaced main content successfully with tabs logic.');
} else {
  console.log('Could not find main tags.');
}
